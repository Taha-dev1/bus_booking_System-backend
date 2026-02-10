# API Reference

**Base URL**: `https://<your-domain>/api`

## Authentication

Most endpoints require a JSON Web Token (JWT) in the header.

**Header Format**:
`Authorization: Bearer <your_access_token>`

---

## 1. Authentication

### Register
**URL**: `/register/`
**Method**: `POST`
**Auth**: None
**Body**:
```json
{
  "email": "user@example.com",
  "name": "John Doe"
  // "password": "..." (Optional if utilizing OTP flow)
}
```

### Login
**URL**: `/login/`
**Method**: `POST`
**Auth**: None
**Body**:
```json
{
  "email": "user@example.com"
}
```
**Response**: Triggers OTP email.

### Admin Login
**URL**: `/admin/login/`
**Method**: `POST`
**Auth**: None
**Body**:
```json
{
  "email": "admin@example.com",
  "password": "your_password"
}
```
**Response**:
```json
{
  "access": "jwt_token...",
  "refresh": "jwt_token...",
  "user": { "role": "admin", ... }
}
```


### Verify Login OTP
**URL**: `/verify-login-otp/`
**Method**: `POST`
**Auth**: None
**Body**:
```json
{
  "email": "user@example.com",
  "otp": "123456"
}
```
**Response**:
```json
{
  "access": "jwt_access_token_string",
  "refresh": "jwt_refresh_token_string",
  "user": { ... }
}
```

---

## 2. Public Leads

### Create Quote Request
**URL**: `/lead/`
**Method**: `POST`
**Auth**: None
**Description**: Creates a new lead (quote request). Logic handles user creation if email is new.

**Request Body**:
```json
{
  "pickup_location": "Dublin, Ireland",
  "dropoff_location": "Cork, Ireland",
  "travel_date": "2024-05-20",
  "pickup_time": "09:00",
  "number_of_passengers": 30,
  "vehicle_type": "Bus",
  "is_roundtrip": true,
  
  "name": "Alice Smith",
  "email": "alice@school.edu",
  "phone_number": "+353871234567",
  "institute_name": "St. Mary's School",

  // OUTBOUND TRIP (Detailed)
  "outbound_trip": {
    "pickup_location": "Dublin, Ireland",
    "dropoff_location": "Cork, Ireland",
    "pickup_date": "2024-05-20",
    "pickup_time": "09:00",
    "trip_stops": [
      {
        "location": "Kildare Service Station",
        "stop_order": 1,
        "estimated_time": 15
      }
    ]
  },

  // RETURN TRIP (If Roundtrip)
  "return_trip": {
    "pickup_location": "Cork, Ireland",
    "dropoff_location": "Dublin, Ireland",
    "pickup_date": "2024-05-20",
    "pickup_time": "18:00",
    "trip_stops": []
  }
}
```

---

## 3. User Leads ("My Leads")

### List My Leads
**URL**: `/leads/`
**Method**: `GET`
**Auth**: Required (User)
**Parameters**:
- `status` (optional): Filter by 'PENDING', 'BOOKED', 'ACCEPTED', 'COMPLETED', etc.
- `sort` (optional): Field to sort by (e.g. `travel_date`).
- `order` (optional): `asc` or `desc`.

**Response**:
```json
{
  "count": 10,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 101,
      "status": "ACCEPTED",
      "pickup_location": "...",
      "estimated_price": 550.00,
      "outbound_trip": { ... },
      "return_trip": { ... }
    }
  ]
}
```

---

## 4. Admin Lead Management

### List All Leads
**URL**: `/admin/leads/`
**Method**: `GET`
**Auth**: Required (Admin)
**Description**: Full list of leads for management. Supports search and filter.

### Update Lead Status (Approve/Reject)
**URL**: `/admin/leads/<id>/`
**Method**: `PATCH`
**Auth**: Required (Admin)
**Description**: Updates lead fields. Setting `status` triggers automated emails.

**Approve Payload**:
```json
{
  "status": "ACCEPTED"
}
```
*Triggers "Trip Approved" email and notification.*

**Reject Payload**:
```json
{
  "status": "REJECTED",
  "rejection_reason": "Distance too short for bus hire."
}
```
*Triggers "Trip Rejected" email.*

### Delete Lead
**URL**: `/admin/leads/<id>/`
**Method**: `DELETE`
**Auth**: Required (Admin)

---

## 5. Transactions

**Unified Endpoint**: `/leads/transactions/<lead_id>/`

### List Transactions for Lead
**Method**: `GET`
**Response**: Array of transaction objects.

### Create Transaction
**Method**: `POST`
**Body**:
```json
{
  "stripe_payment_intent_id": "pi_12345...",
  "amount": 100.00,
  "status": "COMPLETED",
  "payment_type": "PARTIAL" // or FULL
}
```
*Note: `lead` ID is taken from URL. Automatically updates Lead status to `BOOKED` if successful.*

### Update Transaction Status
**Method**: `PATCH`
**Body**:
```json
{
  "status": "COMPLETED"
}
```
*Updates all transactions for this lead to the given status. If `COMPLETED`, marks Lead as `COMPLETED`.*

### Delete Pending Transactions
**Method**: `DELETE`
**Description**: Removes all transactions with `status='PENDING'` for this lead.

---

## 6. Communications (Chat)

### Get/Send Messages
**URL**: `/leads/<lead_id>/chat/`
**Method**: `GET` (List messages) or `POST` (Send message)
**POST Body**:
```json
{
  "message": "Hello, is the bus confirmed?"
}
```

### Unread Message Count (Per Lead)
**URL**: `/leads/<lead_id>/chat/unread/`
**Method**: `GET`
**Response**:
```json
{
  "unread_count": 2
}
```

### Full Conversation History
**URL**: `/leads/<lead_id>/conversation/`
**Method**: `GET`
**Response**: Full history with read receipts.

---

## 7. Admin Utilities

### Vehicles
**URL**: `/admin/vehicles/`
**Method**: `GET, POST, PATCH, DELETE`
**Description**: Manage pricing models per vehicle type.

### Email Templates
**URL**: `/email/`
**Method**: `GET, POST`
**Description**: Manage SendGrid templates for automated emails (`lead_accepted`, `lead_rejected`, etc.).

### System Notifications
**URL**: `/admin/notifications/`
**Method**: `GET`
**Description**: Admin alerts (New Lead, Payment Received).

### Xero
**URL**: `/admin/xero/connect/`
**Method**: `GET`
**Description**: Oauth flow for Xero integration. 
