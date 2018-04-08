import base64, datetime, math
from decimal import Decimal
from time import strptime

from django.shortcuts import render_to_response
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import connection, transaction
from django.db.models import F

from chezbob.finance.models import Split, Account
from chezbob.finance.models import Transaction as FinanceTransaction
from chezbob.users.models import User, Barcode, Transaction
from chezbob.users.forms import *
from chezbob.shortcuts import BobMessages, render_bob_messages, render_or_error, redirect_or_error


@login_required
def user_list(request):
  users = list(User.objects.all().order_by("username"))
  return render_to_response('users/user_list.html',
                            {'user': request.user,
                             'title': "Users Overview",
                             'users': users})

@login_required
def user_details_byname(request, username):
  """ Provides a convenience URL to access user details pages by username
      rather than by userid.  The username is not the primary means of
      identifying users because it complications the function of changing a
      username from the userdetails page.  Also, many times it is more
      convenient to look up a user by id.
  """
  users = list(User.objects.filter(username=username))

  messages = BobMessages()
  if len(users) < 1:
    messages.add_error("Error: User %s not found!" % username)
  elif len(users) > 1:
    messages.add_error("Error: Multiple users %s found!" & username)
  else:
    return redirect_or_error(
        reverse(user_details, args=[users[0].id]), messages)

  return render_or_error('users/user_details.html', messages)

@transaction.atomic
def new_transaction(type, bound, user, messages):
  try:
    if not bound.is_valid:
      messages.errors(bound.error)
      return
    tran = Transaction()
    tran.user = user
    bound.set_transaction_fields(tran, messages)
    if messages.has_errors():
      return
    user.balance = F('balance') + tran.value
    if type in ['ADD', 'REFUND', 'DONATION', 'WRITEOFF']: pass
    elif type == 'BUY':
      # Nothing is required in this case.
      pass
    elif type == 'TRANSFER':
      otran = Transaction()
      otran.user = bound.cleaned_data['other_user']
      otran.time = tran.time
      otran.value = -1 * tran.value
      otran.source = "django"
      direction = bound.cleaned_data['direction']
      if direction == 'to':
        otran.type = "TRANSFER FROM " + user.username.upper()
      elif direction == 'from':
        otran.type = "TRANSFER TO " + user.username.upper()
      else:
        messages.error("Unknown transfer direction %s." % [direction])
      otran.save()
      otran.user.balance = F('balance') + otran.value
      if not messages.has_errors():
        otran.user.save()
        messages.note("New transaction generated %s" % unicode(otran))
    elif type == 'REIMBURSE':
      print (bound.cleaned_data)
      ftrans = FinanceTransaction()
      ftrans.date = tran.time
      ftrans.description = "Reimbursing " + user.username + " for " + bound.cleaned_data['note']
      ftrans.auto_generated = False
      ftrans.save()
      toBank = Split()
      toBank.transaction = ftrans
      bank_of_bob_account_id=2
      toBank.account = Account.objects.get(id=bank_of_bob_account_id)
      toBank.amount = -1 * tran.value
      fromOther = Split()
      fromOther.transaction = ftrans
      fromOther.account = bound.cleaned_data['account']
      fromOther.amount = tran.value
      toBank.save()
      fromOther.save()
    else:
      messages.error("Unknown transaction category %s. Cannot add transaction"
                     % [type])
    if not messages.has_errors():
      tran.save()
      user.save()
    messages.note("New transaction generated %s" % unicode(tran))
  except Exception, e: # use AS keyword in 2.6+
    messages.error("Exception while creating new transaction: " + str(e))
    import sys, traceback
    exc_type, exc_value, exc_traceback = sys.exc_info()
    traceback.print_exception(exc_type, exc_value, exc_traceback,
                              limit=2, file=sys.stdout)
    raise

@transaction.atomic
def edit_transaction(bound, tran, messages):
  return messages.error("Edit not supported yet")
  try:
    if not bound.is_valid:
      messages.errors(bound.error)
      return
  except Exception, e: # use AS keyword in 2.6+
    messages.error("Exception while creating new transaction: " + e.message)
    raise


@transaction.atomic
def delete_transaction(tran, messages):
  try:
    type = tran.type.split()[0]
    user = tran.user
    user.balance = F('balance') - tran.value
    if type in ['ADD', 'REFUND', 'DONATION', 'WRITEOFF']: pass
    elif type == 'BUY':
      # Nothing is required in this case.
      pass
    elif type == 'TRANSFER':
      otrans = Transaction.objects.filter(time=tran.time, value=-1*tran.value)
      if len(otrans) == 1:
        otran = otrans[0]
        otran.user.balance = F('balance') - otran.value
        otran.user.save()
        otran.delete()
        messages.note("Transaction %s deleted" % unicode(otran))
      else:
        messages.warning("""Could not uniquely identifiy transaction for
                            inverse side of this transaction.  It must be
                            removed manually.""")
    elif type == 'REIMBURSE':
      messages.error("Delete reimburse transaction not supported yet")
    else:
      messages.error("Unknown transaction category %s. Cannot delete transaction"
                     % [type])
    if not messages.has_errors():
      tran.delete()
      user.save()
      messages.note("Transaction %s deleted" % unicode(tran))
  except Exception as e:
    messages.error("Exception while creating new transaction: " + e.message)
    raise


@login_required
def user_details(request, userid):
  user = User.objects.get(id=userid)
  messages = BobMessages()
  title = "Manage user: " + user.username

  if user is None:
    return error(messages.add_error("Error: Userid %s not found." % userid))

  barcodes = Barcode.objects.filter(user=user.id)

  def make_form(type, title, form, userid=None):
    form_types[type] = {
        'title' : title,
        'type'  : type,
        'form'  : form,
        'fields': form(userid) if userid else form(),
        'show'  : type + "_open" in request.POST,
    }
    if userid:
        form_types[type]['constructor'] = lambda x: form(userid, x)
  form_types = {}
  make_form('BUY',       'Make Buy Transaction', BuyForm, userid)
  make_form('TRANSFER',  'Make Transfer',        TransferForm)
  make_form('ADD',       'Add Cash',             AddUncountedForm)
  make_form('REIMBURSE', 'Issue Reimbursement',  ReimburseForm)
  make_form('REFUND',    'Issue Cash Refund',    RefundForm)
  make_form('DONATION',  'Donate Balance',       DonateForm)
  make_form('WRITEOFF',  'Write-off Balance',    WriteOffForm)

  def get_tran(is_str):
    try:
      tran_id = int(id_str)
    except:
      messages.error("Attempt to delete invalid transaction id %s" % [id_str])
    else:
      tran = Transaction.objects.get(id=tran_id)
      if tran is None:
        messages.error("Transaction id %s not found to delete." % [tran_id])
      else:
        return tran;

  for field_name in request.POST:
    if field_name.startswith("delete_tran_"):
      id_str = field_name[len("delete_tran_"):]
      tran = get_tran(id_str)
      if tran is not None:
        delete_transaction(tran, messages)
        user = User.objects.get(id=userid)
    if field_name.startswith("edit_tran_"):
      id_str = field_name[len("edit_tran_"):]
      tran = get_tran(id_str)
      if tran is not None:
        form_type = tran.type.split()[0]
        if form_type in form_types:
          form = form_types[form_type]
          form['fields'] = form['form'].set_form_fields(tran, messages)
          if not messages.has_errors():
            form['show'] = True
        else:
          messages.error("No edit form for transaction type %s" % [form_type])


  for type in form_types:
    if type + "_save" in request.POST:
      form_type = form_types[type]
      bound = form_type.get('constructor', form_type['form'])(request.POST)
      if bound.data['id'] == 'new':
        new_transaction(type, bound, user, messages)
      else:
        edit_transaction(type, bound, messages)
      user = User.objects.get(id=userid)

  transactions = Transaction.objects.filter(user=user.id).order_by('-time')

  messages['tools'] = form_types.values()

  if "profile_save" in request.POST:
    bound = ProfileForm(request.POST)
    if bound.is_valid():
      user.username   = bound.cleaned_data['username']
      user.nickname   = bound.cleaned_data['nickname']
      user.email      = bound.cleaned_data['email']
      user.disabled   = bound.cleaned_data['disabled']
      user.fraudulent = bound.cleaned_data['fraudulent']
      user.notes      = bound.cleaned_data['notes']
      user.save()
    else:
      messages.errors(bound.errors)

  messages['profile_form'] = ProfileForm({ 'id'         : user.id,
                                           'username'   : user.username,
                                           'nickname'   : user.nickname,
                                           'email'      : user.email,
                                           'password'   : user.password,
                                           'disabled'   : user.disabled,
                                           'fraudulent' : user.fraudulent,
                                           'notes'      : user.notes })

  if "preferences_save" in request.POST:
    bound = PreferencesForm(request.POST)
    if bound.is_valid():
      user.auto_logout                = bound.cleaned_data['auto_logout']
      user.speech                     = bound.cleaned_data['speech']
      user.forget_which_product       = bound.cleaned_data['forget_which_product']
      user.skip_purchase_confirmation = bound.cleaned_data['skip_confirmation']
      user.save()
    else:
      messages.errors(bound.errors)

  messages['preferences_form'] = PreferencesForm(
      { 'auto_logout'          : user.auto_logout,
        'speech'               : user.speech,
        'forget_which_product' : user.forget_which_product,
        'skip_confirmation'    : user.skip_purchase_confirmation, })

  messages['stats_form'] = StatisticsForm({ 'last_purcahse_time' : user.last_purchase_time,
                                            'last_deposit_time' : user.last_deposit_time,
                                            'created_time' : user.created_time,
                                            'balance' : user.balance, })

  return render_to_response('users/user_details.html',
                            messages.extend({ 'user'          : request.user,
                                              'title'         : title,
                                              'user_detailed' : user,
                                              'barcodes'      : barcodes,
                                              'transactions'  : transactions,}))
