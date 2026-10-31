from django.http import HttpResponse


def home(request):
    return HttpResponse("Sales Insights is running.")