
class XeroToken(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='xero_token')
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    tenant_id = models.CharField(max_length=255, blank=True, null=True)
    scope = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Xero Token for {self.user.email}"
