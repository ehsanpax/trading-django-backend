from django.db import models

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
