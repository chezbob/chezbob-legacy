from datetime import datetime

from django import forms

from chezbob.bobdb.models import DynamicProduct
from chezbob.finance.models import Account
from chezbob.users.models import User


class ProfileForm(forms.Form):
    id          = forms.CharField(
        widget=forms.TextInput(attrs={'readonly': 'readonly'}), required=False)
    username    = forms.CharField()
    nickname    = forms.CharField(required=False)
    email       = forms.EmailField()
    password    = forms.CharField(
        widget=forms.TextInput(attrs={'readonly': 'readonly'}), required=False)
    disabled    = forms.BooleanField(required=False)
    fraudulent  = forms.BooleanField(required=False)
    notes       = forms.CharField(required=False, widget=forms.Textarea)


class PreferencesForm(forms.Form):
    auto_logout                    = forms.BooleanField(required=False)
    speech                             = forms.BooleanField(required=False)
    forget_which_product = forms.BooleanField(required=False)
    skip_confirmation        = forms.BooleanField(required=False)


class StatisticsForm(forms.Form):
    last_purcahse_time  = forms.CharField(
        widget=forms.TextInput(attrs={'disabled': 'disabled'}), required=False)
    last_deposit_time   = forms.CharField(
        widget=forms.TextInput(attrs={'disabled': 'disabled'}), required=False)
    created_time        = forms.CharField(
        widget=forms.TextInput(attrs={'disabled': 'disabled'}), required=False)
    balance             = forms.CharField(
        widget=forms.TextInput(attrs={'disabled': 'disabled'}))


class UserTransactionForm(forms.Form):
    id      = forms.CharField(initial="new", widget=forms.HiddenInput)
    time    = forms.DateTimeField(initial=datetime.now)


class BuyForm(UserTransactionForm):
    #barcode     = forms.ModelChoiceField(
    #    queryset=Product.objects.all().order_by("name"))
    barcode     = forms.ModelChoiceField(queryset=None)
    price       = forms.DecimalField(
        required=False, help_text="Leave empty for current price.")

    def __init__(self, userid, *args, **kwargs):
            super(BuyForm, self).__init__(*args, **kwargs)
            #self.fields['barcode'].queryset = (
            #    Product.objects.all().order_by("name")
            self.fields['barcode'].queryset = (
                DynamicProduct.objects.filter(userid=userid).order_by("name"))

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.barcode = self.cleaned_data['barcode'].barcode
            if self.cleaned_data['price'] is not None:
                transaction.value = -1 * self.cleaned_data['price']
            else:
                transaction.value = -1 * self.cleaned_data['barcode'].price
            transaction.source = "django"
            transaction.type = "BUY " + self.cleaned_data['barcode'].name
            if transaction.value > 0:
                transaction.type = "ADD " + self.cleaned_data['barcode'].name
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        return BuyForm({'id': transaction.id,
                        'time': transaction.time,
                        'price': -1 * transaction.value,
                        'barcode': transaction.barcode.barcode, })


class TransferForm(UserTransactionForm):
    ammount        = forms.DecimalField()
    direction    = forms.ChoiceField(choices=[('to', 'to'), ('from', 'from')],
                                     required=True)
    other_user = forms.ModelChoiceField(
        queryset=User.objects.all().order_by("username"),
        required=True)

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.source = "django"
            other = self.cleaned_data['other_user']
            direction = self.cleaned_data['direction']
            if direction == 'to':
                transaction.value = -1 * self.cleaned_data['ammount']
                transaction.type = "TRANSFER TO " + other.username.upper()
            elif direction == 'from':
                transaction.value = self.cleaned_data['ammount']
                transaction.type = "TRANSFER FROM " + other.username.upper()
            else:
                messages.error("Unknown transfer direction %s." % [direction])
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        messages.warning("""The 'second half' of the transfer transaction is not
                                                yet edited by this form""")
        return BuyForm({'id': transaction.id,
                        'time': transaction.time,
                        'value': transaction.value,
                        'barcode': transaction.barcode, })


class AddUncountedForm(UserTransactionForm):
    ammount        = forms.DecimalField()
    repository = forms.ChoiceField(
        choices=[('chezbob', 'chezbob'),
                 ('soda', 'soda'),
                 ('google_checkout',
                  'google_checkout'),
                 ('other', 'other')],
        required=True)

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.value = self.cleaned_data['ammount']
            transaction.source = self.cleaned_data['repository']
            transaction.type = "ADD"
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        return AddUncountedForm({
            'id': transaction.id,
            'time': transaction.time,
            'ammount': transaction.value,
            'repository': transaction.source,
        })


class ReimburseForm(UserTransactionForm):
    ammount = forms.DecimalField()
    note    = forms.CharField(initial="")
    account = forms.ModelChoiceField(
        queryset=Account.objects.all().order_by("name"), required=True)

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.value = self.cleaned_data['ammount']
            transaction.source = "django"
            transaction.type = (
                "REIMBURSE FROM " + self.cleaned_data['account'].name.upper())
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        str_id = transaction.type.split()[2]
        try:
            account_id = int(str_id)
        except ValueError:
            return messages.error(
                "Reimbursement account id %s invalid" % [str_id])
        else:
            account = Account.objects.get(account_id)
            if account is None:
                messages.warning(
                    "Reimbursement account id %s unrecognized" % [str_id])
            return ReimburseForm({'id': transaction.id,
                                  'time': transaction.time,
                                  'ammount': transaction.value,
                                  'account': account, })


class RefundForm(UserTransactionForm):
    ammount     = forms.DecimalField()
    repository  = forms.ChoiceField(
        choices=[('chezbob', 'chezbob'), ('soda', 'soda')], required=True)

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.value = -1 * self.cleaned_data['ammount']
            transaction.source = self.cleaned_data['repository']
            transaction.type = "REFUND"
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        return RefundForm({'id': transaction.id,
                           'time': transaction.time,
                           'ammount': -1 * transaction.value,
                           'repository': transaction.source})


class DonateForm(UserTransactionForm):
    ammount        = forms.DecimalField()

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.value = -1 * self.cleaned_data['ammount']
            transaction.source = "django"
            transaction.type = "DONATION"
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        return DonateForm({'id': transaction.id,
                           'time': transaction.time,
                           'ammount': transaction.value, })


class WriteOffForm(UserTransactionForm):
    ammount        = forms.DecimalField()

    def set_transaction_fields(self, transaction, messages):
        if self.is_valid():
            transaction.time    = self.cleaned_data['time']
            transaction.value = self.cleaned_data['ammount']
            transaction.source = "django"
            transaction.type = "WRITEOFF"
        else:
            messages.errors(self.errors)

    @classmethod
    def set_form_fields(cls, transaction, messages):
        return WriteOffForm({'id': transaction.id,
                             'time': transaction.time,
                             'ammount': transaction.value})
