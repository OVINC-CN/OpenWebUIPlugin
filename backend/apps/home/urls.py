from apps.home.views import HomeView, I18nViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("", HomeView)
router.register("i18n", I18nViewSet, basename="i18n")

urlpatterns = router.urls
