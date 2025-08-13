from django.db import models
from django.utils.translation import gettext_lazy as _

# Create your models here.
class Currency(models.Model):
    currency =  models.CharField(max_length=200,unique=True)   
    
    def __str__(self):
        return self.currency



class EconomicCalendar(models.Model): 
    event_time = models.DateTimeField(auto_now=False, auto_now_add=False)
    impact = models.CharField(blank=True, null=True) 
    event = models.CharField()
    actual = models.CharField(max_length=200, blank=True, null=True)
    previous = models.CharField(max_length=200, blank=True, null=True)  
    forecast = models.CharField(max_length=200, blank=True, null=True)  
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)  

    def __str__(self):
        return f"{self.event} ({self.impact}) - {self.event_time}"


class News(models.Model):
    headline = models.CharField(_("Headline"), max_length=500, blank=True, null=True)
    time = models.DateTimeField(_("Time"), blank=True, null=True)
    source = models.CharField(_("Source"), max_length=200, blank=True, null=True)
    url = models.URLField(_("URL"), max_length=900, unique=True) 
    content = models.TextField(_("Content"), blank=True, null=True) 

    def __str__(self):
        return self.headline or self.url