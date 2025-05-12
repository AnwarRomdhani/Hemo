"""
URL configuration for Hemo project.

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
from django.contrib import admin
from django.urls import path,include
from django.contrib.auth.views import LoginView, LogoutView
from Hemo.views import add_center , list_centers , superadmin_center_detail , add_center_staff

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', LoginView.as_view(template_name='centers/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),

    
    path('add_center/', add_center, name='add_center'),
    path('centers/', include('centers.urls')),
    path('centers/<int:pk>/', superadmin_center_detail, name='superadmin_center_detail'),
    path('centers/<int:pk>/add_staff/', add_center_staff, name='add_center_staff'),
    path('', list_centers, name='list_centers'),
]
