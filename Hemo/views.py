from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseRedirect
from django import forms
from centers.models import Center, AdministrativeStaff,Delegation,Governorate
from centers.forms import AdministrativeStaffForm  # Use centers.forms
from .forms import CenterForm
import logging
import traceback
import base64
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken


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

@method_decorator(csrf_exempt, name='dispatch')
class AddCenterAPIView(APIView):
    authentication_classes = [BasicAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.debug("CENTER: Received POST request to AddCenterAPIView. User: %s, Data: %s",
                    request.user.username, request.data)

        # Check SUPERADMIN permission
        if not request.user.is_superuser:
            logger.warning("CENTER: Permission denied for user %s. Not a superadmin.", request.user.username)
            return Response({"error": "Permission denied. Only superadmins can add centers."}, status=status.HTTP_403_FORBIDDEN)

        # Validate and save form
        form = CenterForm(request.data)
        if form.is_valid():
            try:
                with transaction.atomic():
                    center = form.save()
                    logger.info("CENTER: Center (ID: %s, Subdomain: %s, Label: %s) added by %s",
                               center.id, center.sub_domain, center.label, request.user.username)
                    return Response(
                        {
                            "success": "Center added successfully.",
                            "center_id": center.id,
                            "sub_domain": center.sub_domain
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("CENTER: Error saving center: %s", str(e))
                return Response({"error": f"Failed to save center: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("CENTER: Center form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)
        

class SuperAdminLoginAPIView(APIView):
    def post(self, request):
        try:
            username = request.data.get('username')
            password = request.data.get('password')

            if not username or not password:
                logger.warning("Missing username or password in SuperAdminLoginAPIView.")
                return Response(
                    {'error': 'Username and password are required.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            user = authenticate(username=username, password=password)
            if not user or not user.is_superuser:
                logger.warning(f"Invalid superadmin login attempt for username: {username}")
                return Response(
                    {'error': 'Invalid credentials or not a superadmin.'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)

            logger.info(f"Superadmin {username} logged in successfully.")
            return Response({
                'success': True,
                'data': {
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'is_superadmin': user.is_superuser
                    }
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in SuperAdminLoginAPIView: {str(e)}")
            return Response(
                {'error': 'An error occurred.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    
@method_decorator(csrf_exempt, name='dispatch')
class CheckSubdomainAPIView(APIView):
    def get(self, request):
        subdomain = request.GET.get('subdomain')
        if not subdomain:
            logger.warning("HEMO: Subdomain check failed: No subdomain provided")
            return Response({"error": "Subdomain is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            Center.objects.get(sub_domain=subdomain)
            logger.debug("HEMO: Subdomain %s exists", subdomain)
            return Response({"success": f"Subdomain {subdomain} exists."}, status=status.HTTP_200_OK)
        except Center.DoesNotExist:
            logger.warning("HEMO: Subdomain %s does not exist", subdomain)
            return Response({"error": f"Subdomain {subdomain} does not exist."}, status=status.HTTP_404_NOT_FOUND)

class CenterListAPIView(APIView):
    def get(self, request):
        try:
            label_filter = request.query_params.get('label', None)
            governorate_id = request.query_params.get('governorate_id', None)
            delegation_id = request.query_params.get('delegation_id', None)

            centers = Center.objects.all()

            if label_filter:
                centers = centers.filter(label__icontains=label_filter)
            if governorate_id:
                centers = centers.filter(governorate__id=governorate_id)
            if delegation_id:
                centers = centers.filter(delegation__id=delegation_id)

            # Manually construct response data
            centers_data = []
            for center in centers:
                center_data = {
                    'id': center.id,
                    'sub_domain': center.sub_domain,
                    'label': center.label,
                    'tel': center.tel,
                    'mail': center.mail,
                    'adresse': center.adresse,
                    'type_center': center.type_center,
                    'code_type_hemo': center.code_type_hemo,
                    'name_type_hemo': center.name_type_hemo,
                    'center_code': center.center_code,
                    'governorate': {
                        'id': center.governorate.id,
                        'label': center.governorate.name,  # Use name instead of label
                        'code': center.governorate.code
                    } if center.governorate else None,
                    'delegation': {
                        'id': center.delegation.id,
                        'label': center.delegation.name,  # Use name instead of label
                        'code': center.delegation.code,
                        'governorate': center.delegation.governorate.id
                    } if center.delegation else None
                }
                centers_data.append(center_data)

            logger.info(f"Retrieved {len(centers)} centers with filters: label={label_filter}, governorate_id={governorate_id}, delegation_id={delegation_id}")
            return Response({'success': True, 'data': centers_data}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in CenterListAPIView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class GovernorateListAPIView(APIView):
    def get(self, request):
        try:
            governorates = Governorate.objects.all()
            # Manually construct response data
            governorates_data = [
                {
                    'id': gov.id,
                    'label': gov.name,  # Use name as label
                    'code': gov.code
                }
                for gov in governorates
            ]
            logger.info(f"Retrieved {len(governorates)} governorates")
            return Response({'success': True, 'data': governorates_data}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in GovernorateListAPIView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class DelegationListAPIView(APIView):
    def get(self, request):
        try:
            delegations = Delegation.objects.all()
            # Manually construct response data
            delegations_data = [
                {
                    'id': delg.id,
                    'label': delg.name,  # Use name as label
                    'code': delg.code,
                    'governorate': delg.governorate.id
                }
                for delg in delegations
            ]
            logger.info(f"Retrieved {len(delegations)} delegations")
            return Response({'success': True, 'data': delegations_data}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in DelegationListAPIView: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class SuperAdminLoginAPIView(APIView):
    def post(self, request):
        try:
            # Extract username and password from request body
            username = request.data.get('username')
            password = request.data.get('password')

            if not username or not password:
                logger.warning("Missing username or password in SuperAdminLoginAPIView.")
                return Response(
                    {'error': 'Username and password are required.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Authenticate user
            user = authenticate(request, username=username, password=password)
            if not user or not user.is_superuser:
                logger.warning(f"Invalid superadmin login attempt for username: {username}")
                return Response(
                    {'error': 'Invalid credentials or not a superadmin.'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            logger.info(f"Superadmin {username} logged in successfully with JWT.")

            return Response({
                'success': True,
                'data': {
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'email': user.email,
                        'is_superadmin': user.is_superuser
                    },
                    'access_token': str(refresh.access_token),
                    'refresh_token': str(refresh)
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in SuperAdminLoginAPIView: {str(e)}")
            return Response(
                {'error': 'An error occurred.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )