from django.urls import path

from .views import dashboard

app_name = "operator_panel"

urlpatterns = [
    path("", dashboard, name="dashboard"),
]
