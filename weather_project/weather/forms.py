from django import forms

class CityForm(forms.Form):
    city = forms.CharField(
        label='City', max_length=100, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Mumbai or Delhi,IN', 'id': 'city-input'})
    )
    units = forms.ChoiceField(
        label='Units',
        choices=[('metric','Celsius (°C)'),('imperial','Fahrenheit (°F)')],
        initial='metric',
        widget=forms.Select(attrs={'id': 'units-select'})
    )
    # lat/lon are optional; JavaScript will redirect with them in query params
    lat = forms.CharField(widget=forms.HiddenInput(), required=False)
    lon = forms.CharField(widget=forms.HiddenInput(), required=False)
