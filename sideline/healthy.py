from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def health_check(request):
    return JsonResponse({
        "status": "ok",
        "service": "sideline-backend"
    })
