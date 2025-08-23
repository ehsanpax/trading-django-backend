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
    
    
   

class COTReport(models.Model):
    # Meta Information
    market_and_exchange_names = models.CharField(max_length=255)
    as_of_date_yyymmdd = models.CharField(max_length=6)
    as_of_date = models.DateField()
    cftc_contract_market_code = models.CharField(max_length=20)
    cftc_market_code_initials = models.CharField(max_length=10)
    cftc_region_code = models.CharField(max_length=10)
    cftc_commodity_code = models.CharField(max_length=20)

    # Open Interest
    open_interest_all = models.IntegerField()
    open_interest_old = models.IntegerField()
    open_interest_other = models.IntegerField()

    # Noncommercial Positions
    noncomm_long_all = models.IntegerField()
    noncomm_short_all = models.IntegerField()
    noncomm_spread_all = models.IntegerField()

    noncomm_long_old = models.IntegerField()
    noncomm_short_old = models.IntegerField()
    noncomm_spread_old = models.IntegerField()

    noncomm_long_other = models.IntegerField()
    noncomm_short_other = models.IntegerField()
    noncomm_spread_other = models.IntegerField()

    # Commercial Positions
    comm_long_all = models.IntegerField()
    comm_short_all = models.IntegerField()
    comm_long_old = models.IntegerField()
    comm_short_old = models.IntegerField()
    comm_long_other = models.IntegerField()
    comm_short_other = models.IntegerField()

    # Total Reportable Positions
    total_reportable_long_all = models.IntegerField()
    total_reportable_short_all = models.IntegerField()
    total_reportable_long_old = models.IntegerField()
    total_reportable_short_old = models.IntegerField()
    total_reportable_long_other = models.IntegerField()
    total_reportable_short_other = models.IntegerField()

    # Nonreportable Positions
    nonreportable_long_all = models.IntegerField()
    nonreportable_short_all = models.IntegerField()
    nonreportable_long_old = models.IntegerField()
    nonreportable_short_old = models.IntegerField()
    nonreportable_long_other = models.IntegerField()
    nonreportable_short_other = models.IntegerField()

    # Changes
    change_open_interest_all = models.IntegerField()
    change_noncomm_long_all = models.IntegerField()
    change_noncomm_short_all = models.IntegerField()
    change_noncomm_spread_all = models.IntegerField()
    change_comm_long_all = models.IntegerField()
    change_comm_short_all = models.IntegerField()
    change_total_reportable_long_all = models.IntegerField()
    change_total_reportable_short_all = models.IntegerField()
    change_nonreportable_long_all = models.IntegerField()
    change_nonreportable_short_all = models.IntegerField()

    # Percentages
    pct_oi_all = models.FloatField()
    pct_noncomm_long_all = models.FloatField()
    pct_noncomm_short_all = models.FloatField()
    pct_noncomm_spread_all = models.FloatField()
    pct_comm_long_all = models.FloatField()
    pct_comm_short_all = models.FloatField()
    pct_total_reportable_long_all = models.FloatField()
    pct_total_reportable_short_all = models.FloatField()
    pct_nonreportable_long_all = models.FloatField()
    pct_nonreportable_short_all = models.FloatField()

    pct_oi_old = models.FloatField()
    pct_noncomm_long_old = models.FloatField()
    pct_noncomm_short_old = models.FloatField()
    pct_noncomm_spread_old = models.FloatField()
    pct_comm_long_old = models.FloatField()
    pct_comm_short_old = models.FloatField()
    pct_total_reportable_long_old = models.FloatField()
    pct_total_reportable_short_old = models.FloatField()
    pct_nonreportable_long_old = models.FloatField()
    pct_nonreportable_short_old = models.FloatField()

    pct_oi_other = models.FloatField()
    pct_noncomm_long_other = models.FloatField()
    pct_noncomm_short_other = models.FloatField()
    pct_noncomm_spread_other = models.FloatField()
    pct_comm_long_other = models.FloatField()
    pct_comm_short_other = models.FloatField()
    pct_total_reportable_long_other = models.FloatField()
    pct_total_reportable_short_other = models.FloatField()
    pct_nonreportable_long_other = models.FloatField()
    pct_nonreportable_short_other = models.FloatField()

    # Traders
    traders_total_all = models.IntegerField()
    traders_noncomm_long_all = models.IntegerField()
    traders_noncomm_short_all = models.IntegerField()
    traders_noncomm_spread_all = models.IntegerField()
    traders_comm_long_all = models.IntegerField()
    traders_comm_short_all = models.IntegerField()
    traders_total_reportable_long_all = models.IntegerField()
    traders_total_reportable_short_all = models.IntegerField()

    traders_total_old = models.IntegerField()
    traders_noncomm_long_old = models.IntegerField()
    traders_noncomm_short_old = models.IntegerField()
    traders_noncomm_spread_old = models.IntegerField()
    traders_comm_long_old = models.IntegerField()
    traders_comm_short_old = models.IntegerField()
    traders_total_reportable_long_old = models.IntegerField()
    traders_total_reportable_short_old = models.IntegerField()

    traders_total_other = models.IntegerField()
    traders_noncomm_long_other = models.IntegerField()
    traders_noncomm_short_other = models.IntegerField()
    traders_noncomm_spread_other = models.IntegerField()
    traders_comm_long_other = models.IntegerField()
    traders_comm_short_other = models.IntegerField()
    traders_total_reportable_long_other = models.IntegerField()
    traders_total_reportable_short_other = models.IntegerField()

    # Concentration (Gross & Net, 4 & 8 TDR)
    conc_gross_4_long_all = models.FloatField()
    conc_gross_4_short_all = models.FloatField()
    conc_gross_8_long_all = models.FloatField()
    conc_gross_8_short_all = models.FloatField()
    conc_net_4_long_all = models.FloatField()
    conc_net_4_short_all = models.FloatField()
    conc_net_8_long_all = models.FloatField()
    conc_net_8_short_all = models.FloatField()

    conc_gross_4_long_old = models.FloatField()
    conc_gross_4_short_old = models.FloatField()
    conc_gross_8_long_old = models.FloatField()
    conc_gross_8_short_old = models.FloatField()
    conc_net_4_long_old = models.FloatField()
    conc_net_4_short_old = models.FloatField()
    conc_net_8_long_old = models.FloatField()
    conc_net_8_short_old = models.FloatField()

    conc_gross_4_long_other = models.FloatField()
    conc_gross_4_short_other = models.FloatField()
    conc_gross_8_long_other = models.FloatField()
    conc_gross_8_short_other = models.FloatField()
    conc_net_4_long_other = models.FloatField()
    conc_net_4_short_other = models.FloatField()
    conc_net_8_long_other = models.FloatField()
    conc_net_8_short_other = models.FloatField()

    # Contract Units & Codes
    contract_units = models.CharField(max_length=255)
    cftc_contract_market_code_quotes = models.CharField(max_length=20)
    cftc_market_code_initials_quotes = models.CharField(max_length=10)
    cftc_commodity_code_quotes = models.CharField(max_length=20)

    # Report Type & Date
    report_type = models.CharField(max_length=50)
    cot_date = models.DateField()

    def __str__(self):
        return f"{self.market_and_exchange_names} - {self.cot_date}"    