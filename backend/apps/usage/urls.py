from apps.usage.views import UsageViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("usages", UsageViewSet)

urlpatterns = router.urls
