
import chezbob.cashout.views as cbv

from django.conf.urls import *

urlpatterns = [
    url(r'^(\d+)/$', cbv.edit_cashout),
    url(r'^new/$', cbv.edit_cashout),
    url(r'^ledger/$', cbv.ledger),
    url(r'^onhand/$', cbv.cashonhand),
    url(r'^$', cbv.ledger),
    url(r'gen_tr/(\d+)/$', cbv.gen_transaction),
    url(r'^losses/$', cbv.show_losses),
]
