import os
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from xero_python.api_client import ApiClient
from xero_python.api_client.configuration import Configuration
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.identity import IdentityApi
from xero_python.accounting import AccountingApi, Contact, Invoice, Invoices, LineItem, LineAmountTypes, CurrencyCode, Organisation, Payment, Payments, Account
from requests_oauthlib import OAuth2Session
from django.core.mail import EmailMessage
import requests

from .models import XeroToken

logger = logging.getLogger(__name__)


class XeroManager:
    def __init__(self, user):
        self.user = user
        self.client_id = os.environ["XERO_CLIENT_ID"]
        self.client_secret = os.environ["XERO_CLIENT_SECRET"]
        self.redirect_uri = os.environ["XERO_REDIRECT_URI"]

        self.scopes = (
            "offline_access "
            "accounting.transactions "
            "accounting.contacts "
            "accounting.settings"
        )

    # --------------------------------------------------
    # TOKEN HELPERS
    # --------------------------------------------------

    def get_token(self):
        try:
            return XeroToken.objects.get(user=self.user)
        except XeroToken.DoesNotExist:
            return None

    def refresh_token_if_needed(self, token):
        if token.expires_at > timezone.now() + timedelta(minutes=5):
            return token

        oauth = OAuth2Session(
            self.client_id,
            token={"refresh_token": token.refresh_token},
        )

        new_token = oauth.refresh_token(
            "https://identity.xero.com/connect/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

        token.access_token = new_token["access_token"]
        token.refresh_token = new_token["refresh_token"]
        token.expires_at = timezone.now() + timedelta(seconds=new_token["expires_in"])
        token.save()

        return token

    # --------------------------------------------------
    # AUTHORIZATION
    # --------------------------------------------------

    def get_authorization_url(self, request):
        oauth = OAuth2Session(
            self.client_id,
            scope=self.scopes.split(),
            redirect_uri=self.redirect_uri,
        )

        auth_url, state = oauth.authorization_url(
            "https://login.xero.com/identity/connect/authorize"
        )

        request.session["xero_oauth_state"] = state
        return auth_url

    def exchange_code_for_token(self, code):
        oauth = OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
        )

        token = oauth.fetch_token(
            "https://identity.xero.com/connect/token",
            code=code,
            client_secret=self.client_secret,
        )

        return token

    # --------------------------------------------------
    # API CLIENT (THIS FIXES YOUR ERROR)
    # --------------------------------------------------
    def get_authenticated_client(self):
        token = self.get_token()
        if not token:
            logger.error("No Xero token found")
            return None

        token = self.refresh_token_if_needed(token)

        # Correct config using OAuth2Token object
        expires_in = int((token.expires_at - timezone.now()).total_seconds())
        oauth2_token = OAuth2Token()
        oauth2_token.access_token = token.access_token
        oauth2_token.refresh_token = token.refresh_token
        oauth2_token.expires_at = int(token.expires_at.timestamp())
        oauth2_token.token_type = "Bearer"
        oauth2_token.scope = token.scope
        oauth2_token.expires_in = expires_in

        config = Configuration(oauth2_token=oauth2_token)
        
        def token_getter():
            return {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": int(token.expires_at.timestamp()),
                "token_type": "Bearer",
                "scope": token.scope,
                "expires_in": expires_in,
            }

        client = ApiClient(configuration=config, oauth2_token_getter=token_getter)
        return client

    # --------------------------------------------------
    # TENANT ID
    # --------------------------------------------------

    def get_tenant_id(self):
        token = self.get_token()
        if token and token.tenant_id:
            return token.tenant_id

        client = self.get_authenticated_client()
        if not client:
            raise Exception("Xero client not authenticated")

        identity_api = IdentityApi(client)
        connections = identity_api.get_connections()

        if not connections:
            raise Exception("No Xero tenants found")

        tenant_id = connections[0].tenant_id
        token.tenant_id = tenant_id
        token.save()

        return tenant_id

    # --------------------------------------------------
    # INVOICE
    # --------------------------------------------------

    def create_invoice_for_lead(self, lead, amount):
        client = self.get_authenticated_client()
        if not client:
            logger.error("No authenticated Xero client.")
            return None, "Not authenticated with Xero"

        tenant_id = self.get_tenant_id()
        if not tenant_id:
            logger.error("No Xero tenant ID found.")
            return None, "No Xero Tenant ID found"

        accounting = AccountingApi(client)

        # --------------------------------------------------
        # Fetch organisation currency
        # --------------------------------------------------
        try:
            org_response = accounting.get_organisations(xero_tenant_id=tenant_id)
            if org_response.organisations and len(org_response.organisations) > 0:
                base_currency = org_response.organisations[0].base_currency
                currency_enum = CurrencyCode(base_currency)
                logger.info(f"Organisation currency detected: {base_currency}")
            else:
                logger.warning("No organisation found, falling back to USD")
                currency_enum = CurrencyCode.USD
        except Exception as e:
            logger.error(f"Failed to fetch organisation currency: {e}")
            currency_enum = CurrencyCode.USD  # fallback

        # --------------------------------------------------
        # Create contact
        # --------------------------------------------------
        contact = Contact(
            name=lead.name,
            email_address=lead.email,
        )

        # --------------------------------------------------
        # Create line item
        # --------------------------------------------------
        line_item = LineItem(
            description=f"Transport Service - Quote #{lead.id}",
            quantity=1,
            unit_amount=float(amount),
            account_code="200",  # Sales account
        )

        # --------------------------------------------------
        # Create invoice
        # --------------------------------------------------
        invoice = Invoice(
            type="ACCREC",
            contact=contact,
            date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=7),
            line_items=[line_item],
            status="AUTHORISED",
            reference=f"Ref-Lead-{lead.id}",
            currency_code=currency_enum,           # Use organisation currency
            line_amount_types=LineAmountTypes.INCLUSIVE  # Use enum
        )

        # Log the invoice before sending
        logger.info(f"Creating Xero invoice: {invoice}")

        try:
            # Wrap in Invoices model to ensure correct serialization
            invoices_container = Invoices(invoices=[invoice])
            response = accounting.create_invoices(
                xero_tenant_id=tenant_id,
                invoices=invoices_container,
            )
            created_invoice = response.invoices[0]
            logger.info(f"Xero Invoice created: {created_invoice.invoice_number}")
            return created_invoice, None
        except Exception as e:
            logger.error(f"Xero Invoice Creation Failed: {e}")
            return None, str(e)

    def email_invoice_pdf(self, invoice_id, lead):
        """
        Fetches PDF from Xero and emails it to the user.
        """
        client = self.get_authenticated_client()
        if not client:
            return False

        tenant_id = self.get_tenant_id()
        accounting_api = AccountingApi(client)

        try:
            # Get PDF content (Xero SDK may return a file path string or bytes)
            pdf_result = accounting_api.get_invoice_as_pdf(
                xero_tenant_id=tenant_id,
                invoice_id=invoice_id
            )

            # If it's a file path string, read the binary content
            if isinstance(pdf_result, str):
                with open(pdf_result, 'rb') as f:
                    pdf_content = f.read()
            else:
                pdf_content = pdf_result

            # Send Email
            subject = f"Invoice for Trip #{lead.id}"
            body = f"Dear {lead.name},\n\nPlease find attached the invoice for your recent trip payment.\n\nBest regards,\nTransport Team"

            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[lead.email],
            )

            filename = f"Invoice-{invoice_id}.pdf"
            # Send email and update lead status atomically
            with transaction.atomic():
                email.attach(filename, pdf_content, 'application/pdf')
                email.send(fail_silently=False)
                logger.info(f"Invoice PDF sent to {lead.email}")

                # Update lead status
                lead.invoice_sent = True
                lead.save(update_fields=['invoice_sent'])

            return True

        except Exception as e:
            logger.error(f"Failed to fetch/email PDF invoice: {e}")
            return False

    def get_invoice_by_lead(self, lead):
        """
        Finds an invoice in Xero for the given lead by matching the reference.
        """
        logger.debug(f"Searching for invoice for lead ID: {lead.id}")
        client = self.get_authenticated_client()
        if not client:
            return None

        tenant_id = self.get_tenant_id()
        accounting_api = AccountingApi(client)

        try:
            # Search for invoice with matching reference
            # Xero API supports filtering by where clause
            where_clause = f'Reference=="Ref-Lead-{lead.id}"'
            invoices_response = accounting_api.get_invoices(
                xero_tenant_id=tenant_id,
                where=where_clause
            )
            
            if invoices_response.invoices:
                # Return the first matching invoice
                return invoices_response.invoices[0]
            
            return None

        except Exception as e:
            logger.error(f"Failed to find invoice for lead {lead.id}: {e}")
            return None

    # --------------------------------------------------
    # PAYMENT
    # --------------------------------------------------

    def create_payment(self, invoice_id, amount, account_code="090078601"):
        """
        Creates a payment for the given invoice ID in Xero.
        Default account code: 090078601 (Bank Account)
        """
        client = self.get_authenticated_client()
        if not client:
            return None, "Not authenticated with Xero"

        tenant_id = self.get_tenant_id()
        accounting_api = AccountingApi(client)

        # Validate account identifier
        if not account_code or not isinstance(account_code, str) or len(account_code.strip()) == 0:
            error_msg = "Invalid account code provided"
            logger.error(error_msg)
            return None, error_msg

        account_code = account_code.strip()

        try:
            # Create Invoice Wrapper
            invoice_wrapper = Invoice(invoice_id=invoice_id)

            # Create Payment Object - using account code (short alphanumeric)
            payment = Payment(
                invoice=invoice_wrapper,
                account=Account(code=account_code),
                amount=float(amount),
                date=timezone.now().date(),
                reference="Payment via Admin Panel"
            )

            # Create Payments container
            payments_container = Payments(payments=[payment])

            # Send to Xero
            result = accounting_api.create_payments(
                xero_tenant_id=tenant_id,
                payments=payments_container
            )

            # Defensive check for payments result
            if not hasattr(result, 'payments') or not result.payments or len(result.payments) == 0:
                error_msg = f"No payments returned from Xero API for invoice {invoice_id}"
                logger.error(error_msg)
                return None, error_msg

            created_payment = result.payments[0]
            logger.info(f"Payment created for Invoice ID {invoice_id}: {created_payment.payment_id}")
            return created_payment, None

        except Exception as e:
            logger.error(f"Failed to create payment in Xero: {e}")
            return None, str(e)
