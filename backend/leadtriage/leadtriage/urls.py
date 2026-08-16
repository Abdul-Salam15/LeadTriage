"""
URL configuration for leadtriage project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path
from pathlib import Path


def healthz(request):
    """Liveness probe for Render / load balancers."""
    return JsonResponse({"status": "ok"})


def index(request):
    """Serve the built React SPA (index.html) at the site root."""
    candidates = list(settings.STATICFILES_DIRS) + [settings.STATIC_ROOT]
    for base in candidates:
        index_path = Path(base) / "index.html"
        if index_path.exists():
            return FileResponse(index_path.open("rb"), content_type="text/html")
    raise Http404("Frontend has not been built. Run the frontend build first.")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("api/v1/", include("api.urls")),
    # Everything else (non-API, non-static, non-admin) -> the SPA shell.
    re_path(r"^(?!api/|admin/|static/|media/|healthz).*$", index, name="index"),
]
