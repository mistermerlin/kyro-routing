from django.http import HttpResponse

from tests.otherapp import router


@router.route("/other", name="other")
def other(request):
    return HttpResponse("other")
