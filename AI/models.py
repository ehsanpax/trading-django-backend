from django.db import models
from django.contrib.auth.models import User

class Prompt(models.Model):
    name = models.CharField(max_length=255)
    prompt = models.TextField()
    version = models.CharField(max_length=50)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_prompts')
    is_globally_shared = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} (v{self.version})"

    class Meta:
        unique_together = ('name', 'version', 'user')
