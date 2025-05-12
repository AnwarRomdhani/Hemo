from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseRedirect
from django import forms
from centers.models import Center, AdministrativeStaff
from centers.forms import AdministrativeStaffForm  # Use centers.forms
from .forms import CenterForm
import logging
import traceback

logger = logging.getLogger(__name__)

def is_superadmin(user):
    return user.is_authenticated and user.is_superuser

def SuperAdminLoginView(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_superuser:
            if not AdministrativeStaff.objects.filter(user=user).exists():
                login(request, user)
                logger.info("HEMO: Superadmin logged in: %s", username)
                return HttpResponseRedirect('list_centers')
            else:
                logger.warning("HEMO: Center staff attempted superadmin login: %s", username)
                return render(request, 'Hemo/login.html', {
                    'error': 'This account is for center staff, not superadmin.'
                })
        else:
            logger.warning("HEMO: Failed superadmin login attempt: %s", username)
            return render(request, 'Hemo/login.html', {
                'error': 'Invalid username or password, or not a superuser.'
            })
    return render(request, 'Hemo/login.html')

@user_passes_test(is_superadmin)
def list_centers(request):
    if hasattr(request, 'tenant') and request.tenant:
        return redirect('center_detail')
    centers = Center.objects.all().order_by('label')
    return render(request, 'Hemo/list_centers.html', {
        'centers': centers
    })

@user_passes_test(is_superadmin)
def superadmin_center_detail(request, pk):
    center = get_object_or_404(Center, pk=pk)
    return render(request, 'Hemo/superadmin_center_detail.html', {
        'center': center,
        'technical_staff': center.technical_staff.all(),
        'medical_staff': center.medical_staff.all(),
        'paramedical_staff': center.paramedical_staff.all(),
        'patients': center.patient_staff.all(),
    })

@user_passes_test(is_superadmin)
def add_center(request):
    center_id = request.GET.get('center_id')
    instance = get_object_or_404(Center, pk=center_id) if center_id else None
    if request.method == 'POST':
        form = CenterForm(request.POST, instance=instance)
        logger.debug("HEMO: POST data for add_center: %s", request.POST)
        if form.is_valid():
            logger.info("HEMO: Form is valid, cleaned data: %s", form.cleaned_data)
            try:
                center = form.save()
                logger.info("HEMO: Center saved: %s, Delegation: %s", center, center.delegation)
                if not request.tenant:
                    return redirect('superadmin_center_detail', pk=center.pk)
                return redirect(f"http://{center.sub_domain | default:'center1'}.localhost:8000/")
            except Exception as e:
                logger.error("HEMO: Error saving center: %s\n%s", str(e), traceback.format_exc())
                form.add_error(None, f"Error saving center: {str(e)}")
        else:
            logger.warning("HEMO: Form is invalid: %s", form.errors)
            return render(request, 'Hemo/add_center.html', {'form': form})
    else:
        form = CenterForm(instance=instance)
        logger.debug("HEMO: Rendering form with instance: %s", instance)
    return render(request, 'Hemo/add_center.html', {'form': form})

@user_passes_test(is_superadmin)
def add_center_staff(request, pk):
    center = get_object_or_404(Center, pk=pk)
    logger.debug("HEMO: Accessing Hemo add_center_staff for center %s (ID: %s)", center.label, pk)
    if request.method == 'POST':
        logger.debug("HEMO: Received POST data: %s", dict(request.POST))
        if not any(k for k in request.POST if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Empty POST data received (excluding csrfmiddlewaretoken)")
            form = AdministrativeStaffForm()
            return render(request, 'Hemo/add_center_staff.html', {
                'form': form,
                'center': center,
                'error': 'No form data submitted. Please fill out the form.',
                'form_errors': None,
                'post_data': dict(request.POST)
            })
        form = AdministrativeStaffForm(request.POST)
        if form.is_valid():
            logger.debug("HEMO: Form is valid, cleaned data: %s", form.cleaned_data)
            try:
                staff = form.save(commit=False)
                staff.center = center
                logger.debug("HEMO: Staff user after form.save: %s", staff.user)
                if not staff.user:
                    logger.error("HEMO: No user assigned to staff after form.save")
                    raise ValueError("No user assigned to staff. Ensure username, email, and password are provided.")
                staff.save()
                logger.info("HEMO: New administrative staff %s added to center %s by superadmin %s",
                            f"{staff.nom} {staff.prenom}", center.label, request.user.username)
                return redirect('superadmin_center_detail', pk=center.pk)
            except forms.ValidationError as e:
                logger.error("HEMO: Validation error saving staff: %s\n%s", str(e), traceback.format_exc())
                return render(request, 'Hemo/add_center_staff.html', {
                    'form': form,
                    'center': center,
                    'error': str(e),
                    'form_errors': form.errors,
                    'post_data': dict(request.POST)
                })
            except Exception as e:
                logger.error("HEMO: Unexpected error saving staff: %s\n%s", str(e), traceback.format_exc())
                if "Column 'user_id' cannot be null" in str(e):
                    error_msg = "Failed to save staff: No user was created. Please ensure username, email, and password are valid."
                else:
                    error_msg = f"Unexpected error: {str(e)}"
                return render(request, 'Hemo/add_center_staff.html', {
                    'form': form,
                    'center': center,
                    'error': error_msg,
                    'form_errors': form.errors,
                    'post_data': dict(request.POST)
                })
        else:
            logger.error("HEMO: Administrative staff form is invalid: %s", form.errors.as_json())
            return render(request, 'Hemo/add_center_staff.html', {
                'form': form,
                'center': center,
                'error': 'Please correct the errors below.',
                'form_errors': form.errors,
                'post_data': dict(request.POST)
            })
    else:
        logger.debug("HEMO: Rendering add_center_staff form for center %s", center.label)
        form = AdministrativeStaffForm()
    return render(request, 'Hemo/add_center_staff.html', {
        'form': form,
        'center': center,
    })