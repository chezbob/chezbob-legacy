from django.conf.urls import url, include

from django.contrib import admin

import chezbob.bobdb.views as cbdbv
import chezbob.orders.views as cov
import chezbob.finance.views as cfv
import chezbob.users.views as cuv
import chezbob.query.views as cqv

import chezbob.cashout.urls as cou

from django.contrib.auth.views import login

admin.autodiscover()
urlpatterns = [
    # Chez Bob products, pricing, and inventory
    url(r'^products/$', cbdbv.products),
    url(r'^products/(.+)/$',
        cbdbv.product_detail, name='chezbob.product_detail'),
    #url(r'^products/([0-9]+)/$', cbdbv.product_detail,
    #    name='chezbob.product_detail'),
    #url(r'^orders/([0-9]+)/$', cbdbv.view_order),
    #url(r'^orders/([0-9]+)/update/$', cbdbv.update_order),
    url(r'^orders/$', cov.order_list),
    url(r'^orders/(\d+)/$', cov.order_summary),
    url(r'^orders/new/$', cov.new_order),
    url(r'^sales/$', cbdbv.inventory),
    url(r'^sales/([0-9]+)/$', cbdbv.inventory_detail),

    url(r'^inventory/$', cbdbv.list_inventories),
    url(r'^inventory/(\d{4}-\d{1,2}-\d{1,2})/$', cbdbv.take_inventory),
    url(r'^inventory/(\d{4}-\d{1,2}-\d{1,2} \d{2}:\d{2}:\d{2})/$',
        cbdbv.take_inventory),
    url(r'^inventory/order/$', cbdbv.estimate_order),
    url(r'^inventory/order/print/$', cbdbv.display_order),

    # Accounting
    url(r'^$', cfv.redirect),
    url(r'^finance[/]$', cfv.redirect),
    url(r'^finance/accounts/$', cfv.account_list),
    url(r'^finance/ledger/$', cfv.ledger),
    url(r'^finance/account/(\d+)/$', cfv.ledger),
    url(r'^finance/transaction/(\d+)/$', cfv.edit_transaction),
    url(r'^finance/transaction/new/$', cfv.edit_transaction),
    url(r'^finance/dump/$', cfv.gnuplot_dump),
    url(r'^finance/xactdump/$', cfv.transaction_dump),

    # User Management
    url(r'^users/$', cuv.user_list, name='chezbob.users.views.user_list'),
    url(r'^user/(\w+)/$', cuv.user_details,
        name='chezbob.users.views.user_details'),
    url(r'^username/(\w+)/$', cuv.user_details_byname),

    # Cashout
    url(r'^cashout/', include(cou)),

    # Specialized database queries
    url(r'^query/$', cqv.home),
    url(r'^query/results/(\w+)/$', cqv.results),
    url(r'^query/raw/(\w+)/$', cqv.raw_table),

    # Default admin interface for editing database
    url(r'^django/', admin.site.urls),

    url(r'^accounts/login/$', login, name='django.login'),

    # Uncomment when running on testing server, set correct path for js files
    # (r'^js/(?P<path>.*)$',
    #  'django.views.static.serve',
    #  {'document_root': '/home/nbales/Sources/chezbob.hg/www/js/'}),
]
