import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth import authenticate, login
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from django.contrib.auth.models import User
from django.db.models import Count, Q
from io import BytesIO
from datetime import datetime
from .models import UserProfile,TypeHemo,MethodHemo,Filtre,Membrane, Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, Delegation, Patient, CNAM, MethodHemo, MedicalActivity, TransmittableDiseaseRef, ComplicationsRef, Machine, HemodialysisSession, TransmittableDisease, Complications, Transplantation, TransplantationRef
from .forms import DeceasePatientForm, VerificationForm, TransplantationRefForm, TechnicalStaffForm, MedicalStaffForm, ParamedicalStaffForm, AdministrativeStaffForm, WorkerStaffForm, MachineForm, PatientForm, HemodialysisSessionForm, TransmittableDiseaseForm, TransmittableDiseaseRefForm, ComplicationsForm, ComplicationsRefForm, TransplantationForm
from .utils import send_verification_email
from django.template.loader import render_to_string
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from django.core.exceptions import ObjectDoesNotExist

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.db import IntegrityError
import re
from .permissions import RoleBasedPermission
from .ml.predictor import predict_hemodialysis
import traceback
logger = logging.getLogger(__name__)

class HemodialysisPredictionView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN','MEDICAL_PARA_STAFF']

    def post(self, request):
        data = request.data

        try:
            # Let predict_hemodialysis handle parsing and preparation of features from raw data
            result = predict_hemodialysis(data)
            return Response(result)

        except ValueError as ve:
            # Catch validation errors from predict_hemodialysis and return as 400
            return Response({"error": str(ve)}, status=400)

        except Exception as e:
            tb = traceback.format_exc()
            print(f"Error in HemodialysisPredictionView.post:\n{tb}")
            return Response({"error": "Internal Server Error"}, status=500)

def CenterLoginView(request):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        logger.error("No tenant found for login request")
        return render(request, 'centers/login.html', {
            'error': 'Invalid center subdomain.'
        })

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Handle superadmin
            if user.is_superuser:
                logger.info("Superadmin %s logging in to center %s", username, tenant.label)
                try:
                    profile = user.verification_profile
                    login(request, user)
                    logger.info("Superadmin %s logged in for center %s (verification bypassed)", username, tenant.label)
                    return redirect('center_detail')
                except UserProfile.DoesNotExist:
                    logger.error("No verification profile for superadmin %s", username)
                    return render(request, 'centers/login.html', {
                        'error': 'Verification profile missing. Contact support.'
                    })
            
            # Handle non-superadmin users
            staff_types = [AdministrativeStaff, ParamedicalStaff, TechnicalStaff, MedicalStaff, WorkerStaff]
            staff = None
            for staff_type in staff_types:
                try:
                    staff = staff_type.objects.get(user=user, center=tenant)
                    logger.debug("Found %s for user %s in center %s", staff_type.__name__, username, tenant.label)
                    break
                except staff_type.DoesNotExist:
                    logger.debug("No %s found for user %s in center %s", staff_type.__name__, username, tenant.label)
                    continue
            
            if staff:
                try:
                    profile = user.verification_profile
                    if not profile.is_verified:
                        logger.info("User %s requires email verification", username)
                        request.session['pending_user_id'] = user.id
                        return redirect('verify_email')
                    login(request, user)
                    logger.info("User %s logged in for center %s as %s", username, tenant.label, staff.__class__.__name__)
                    return redirect('center_detail')
                except UserProfile.DoesNotExist:
                    logger.error("No verification profile for user %s", username)
                    return render(request, 'centers/login.html', {
                        'error': 'Verification profile missing. Contact support.'
                    })
            else:
                logger.warning("User %s not authorized for center %s", username, tenant.label)
                return render(request, 'centers/login.html', {
                    'error': 'You are not authorized for this center.'
                })
        else:
            logger.warning("Failed login attempt for username: %s at center %s", username, tenant.label)
            return render(request, 'centers/login.html', {
                'error': 'Invalid username or password.'
            })
    return render(request, 'centers/login.html', {'center': tenant})

def verify_email(request):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        logger.error("No tenant found for verify_email request")
        return render(request, 'centers/404.html', status=404)

    user_id = request.session.get('pending_user_id')
    if not user_id:
        logger.warning("No pending user ID in session for verify_email")
        return redirect('login')

    try:
        user = User.objects.get(id=user_id)
        profile = user.verification_profile
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        logger.error("Invalid user or profile for ID %s", user_id)
        return redirect('login')

    if request.method == 'POST':
        form = VerificationForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['verification_code']
            if profile.verify_code(code):
                login(request, user)
                logger.info("User %s logged in after verification", user.username)
                del request.session['pending_user_id']
                return redirect('center_detail')
            else:
                form.add_error('verification_code', 'Invalid verification code.')
                logger.warning("Failed verification attempt for user %s", user.username)
        else:
            logger.warning("Verification form invalid: %s", form.errors)
    else:
        form = VerificationForm()

    if 'resend' in request.GET:
        new_code = profile.generate_verification_code()
        try:
            send_verification_email(user, new_code)
            logger.info("Resent verification email to %s", user.email)
            return render(request, 'centers/verify_email.html', {
                'form': form,
                'center': tenant,
                'message': 'A new verification code has been sent to your email.'
            })
        except Exception as e:
            logger.error("Failed to resend verification email to %s: %s", user.email, str(e))
            form.add_error(None, 'Failed to resend verification code. Please try again.')

    return render(request, 'centers/verify_email.html', {
        'form': form,
        'center': tenant
    })

def get_user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'SUPERADMIN'
    try:
        if hasattr(user, 'technical_profile'):
            return user.technical_profile.role
        elif hasattr(user, 'medical_profile'):
            return user.medical_profile.role
        elif hasattr(user, 'paramedical_profile'):
            return user.paramedical_profile.role
        elif hasattr(user, 'administrative_profile'):
            return user.administrative_profile.role
        elif hasattr(user, 'worker_profile'):
            return user.worker_profile.role
    except AttributeError:
        return None
    return None
def is_local_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    role = get_user_role(user)
    return role == 'LOCAL_ADMIN'

def is_submitter(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or is_local_admin(user):
        return True
    role = get_user_role(user)
    return role in ['SUBMITTER', 'MEDICAL_PARA_STAFF']
def is_medical_para_staff(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or is_local_admin(user):
        return True
    role = get_user_role(user)
    return role == 'MEDICAL_PARA_STAFF'
def is_viewer(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or is_local_admin(user) or is_submitter(user) or is_medical_para_staff(user):
        return True
    role = get_user_role(user)
    return role == 'VIEWER'


@login_required
def export_pdf(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for export_pdf")
        return HttpResponse("No center found for this subdomain.", status=404)

    patients = Patient.objects.filter(center=center)
    sessions = HemodialysisSession.objects.filter(medical_activity__patient__center=center)
    diseases = TransmittableDisease.objects.filter(medical_activity__patient__center=center)
    complications = Complications.objects.filter(medical_activity__patient__center=center)
    transplantations = Transplantation.objects.filter(medical_activity__patient__center=center)
    deceased_patients = patients.filter(status='DECEASED')
    medical_staff = MedicalStaff.objects.filter(center=center)
    paramedical_staff = ParamedicalStaff.objects.filter(center=center)
    administrative_staff = AdministrativeStaff.objects.filter(center=center)
    technical_staff = TechnicalStaff.objects.filter(center=center)
    worker_staff = WorkerStaff.objects.filter(center=center)
    machines = Machine.objects.filter(center=center)

    context = {
        'center': center,
        'patients': patients,
        'sessions': sessions,
        'diseases': diseases,
        'complications': complications,
        'transplantations': transplantations,
        'deceased_patients': deceased_patients,
        'total_deaths': deceased_patients.count(),
        'medical_staff': medical_staff,
        'paramedical_staff': paramedical_staff,
        'administrative_staff': administrative_staff,
        'technical_staff': technical_staff,
        'worker_staff': worker_staff,
        'machines': machines,
        'total_diseases': diseases.count(),
        'total_complications': complications.count(),
        'report_date': datetime.now().strftime('%Y-%m-%d'),
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="center_report_{center.label}_{context["report_date"]}.pdf"'
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name='Title',
        fontSize=16,
        fontName='Helvetica-Bold',
        alignment=1,
        spaceAfter=12,
    )
    subtitle_style = ParagraphStyle(
        name='Subtitle',
        fontSize=12,
        fontName='Helvetica-Bold',
        textColor=colors.blue,
        leading=14,
        spaceBefore=10,
        spaceAfter=8,
    )
    normal_style = styles['Normal']
    normal_style.fontSize = 10

    elements.append(Paragraph(f"{center.label} - Activity Report", title_style))
    elements.append(Paragraph(f"Date: {context['report_date']}", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Center Information", title_style))
    center_data = [
        ['Name', center.label],
        ['Address', center.adresse],
        ['Delegation', center.delegation.name if center.delegation else 'N/A'],
        ['Telephone', center.tel or 'N/A'],
        ['Email', center.mail or 'N/A'],
    ]
    center_table = Table(center_data, colWidths=[5*cm, 12*cm])
    center_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ('ALIGN', (1,0), (1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(center_table)
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Staff Members", title_style))

    elements.append(Paragraph("Administrative Staff", subtitle_style))
    admin_data = [['Name', 'CIN', 'Details']]
    for staff in administrative_staff:
        admin_data.append([
            f"{staff.nom} {staff.prenom}",
            staff.cin,
            f"Job Title: {staff.job_title}",
        ])
    for staff in technical_staff:
        admin_data.append([
            f"{staff.nom} {staff.prenom}",
            staff.cin,
            f"Qualification: {staff.qualification}",
        ])
    if len(admin_data) > 1:
        admin_table = Table(admin_data, colWidths=[5*cm, 4*cm, 8*cm])
        admin_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(admin_table)
    else:
        elements.append(Paragraph("No Administrative Staff recorded.", normal_style))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(Paragraph("Para & Medical Staff", subtitle_style))
    para_medical_data = [['Name', 'CIN', 'Details']]
    for staff in medical_staff:
        para_medical_data.append([
            f"{staff.nom} {staff.prenom}",
            staff.cin,
            f"CNOM: {staff.cnom}",
        ])
    for staff in paramedical_staff:
        para_medical_data.append([
            f"{staff.nom} {staff.prenom}",
            staff.cin,
            f"Qualification: {staff.qualification}",
        ])
    if len(para_medical_data) > 1:
        para_medical_table = Table(para_medical_data, colWidths=[5*cm, 4*cm, 8*cm])
        para_medical_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(para_medical_table)
    else:
        elements.append(Paragraph("No Para & Medical Staff recorded.", normal_style))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(Paragraph("Workers Staff", subtitle_style))
    worker_data = [['Name', 'CIN', 'Details']]
    for staff in worker_staff:
        worker_data.append([
            f"{staff.nom} {staff.prenom}",
            staff.cin,
            f"Job Title: {staff.job_title}",
        ])
    if len(worker_data) > 1:
        worker_table = Table(worker_data, colWidths=[5*cm, 4*cm, 8*cm])
        worker_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(worker_table)
    else:
        elements.append(Paragraph("No Workers Staff recorded.", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Equipment", title_style))
    machine_data = [['Brand', 'Functional', 'Reserve', 'Refurbished', 'Hours', 'Membrane', 'Filtre']]
    for machine in machines:
        machine_data.append([
            machine.brand,
            'Yes' if machine.functional else 'No',
            'Yes' if machine.reserve else 'No',
            'Yes' if machine.refurbished else 'No',
            str(machine.nbre_hrs),
            machine.membrane.type,
            f"{machine.filtre.type} ({machine.filtre.sterilisation})" if machine.filtre.sterilisation else machine.filtre.type,
        ])
    if len(machine_data) > 1:
        machine_table = Table(machine_data, colWidths=[3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2*cm, 2.5*cm, 3*cm])
        machine_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(machine_table)
    else:
        elements.append(Paragraph("No machines recorded.", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Activity", title_style))
    elements.append(Paragraph("Hemodialysis Sessions", subtitle_style))
    session_data = [['Type', 'Method', 'Date', 'Responsible Doctor']]
    for session in sessions:
        session_data.append([
            session.type.name,
            session.method.name,
            session.date_of_session.strftime('%Y-%m-%d'),
            f"{session.responsible_doc.nom} {session.responsible_doc.prenom}",
        ])
    if len(session_data) > 1:
        session_table = Table(session_data, colWidths=[4*cm, 4*cm, 4*cm, 5*cm])
        session_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(session_table)
    else:
        elements.append(Paragraph("No hemodialysis sessions recorded.", normal_style))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(Paragraph("Transplantations", subtitle_style))
    transplantation_data = [['Type', 'Date of Operation', 'Notes']]
    for transplantation in transplantations:
        transplantation_data.append([
            transplantation.transplantation.label_transplantation,
            transplantation.date_operation.strftime('%Y-%m-%d'),
            transplantation.notes or 'No notes',
        ])
    if len(transplantation_data) > 1:
        transplantation_table = Table(transplantation_data, colWidths=[6*cm, 5*cm, 6*cm])
        transplantation_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(transplantation_table)
    else:
        elements.append(Paragraph("No transplantations recorded.", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Morbidity", title_style))
    elements.append(Paragraph("Transmittable Diseases", subtitle_style))
    disease_data = [['Disease', 'Transmission Type', 'Date of Contraction']]
    for disease in diseases:
        disease_data.append([
            disease.disease.label_disease,
            disease.disease.type_of_transmission,
            disease.date_of_contraction.strftime('%Y-%m-%d'),
        ])
    if len(disease_data) > 1:
        disease_table = Table(disease_data, colWidths=[6*cm, 6*cm, 5*cm])
        disease_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(disease_table)
    else:
        elements.append(Paragraph("No transmittable diseases recorded.", normal_style))
    elements.append(Paragraph(f"Total Incidents: {context['total_diseases']}", normal_style))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(Paragraph("Complications", subtitle_style))
    complication_data = [['Complication', 'Notes', 'Date of Contraction']]
    for complication in complications:
        complication_data.append([
            complication.complication.label_complication,
            complication.notes or 'No notes',
            complication.date_of_contraction.strftime('%Y-%m-%d'),
        ])
    if len(complication_data) > 1:
        complication_table = Table(complication_data, colWidths=[6*cm, 6*cm, 5*cm])
        complication_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(complication_table)
    else:
        elements.append(Paragraph("No complications recorded.", normal_style))
    elements.append(Paragraph(f"Total Incidents: {context['total_complications']}", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Mortality", title_style))
    elements.append(Paragraph("Deceased Patients", subtitle_style))
    deceased_data = [['Name', 'CIN', 'Decease Note']]
    for patient in deceased_patients:
        deceased_data.append([
            f"{patient.nom} {patient.prenom}",
            patient.cin,
            patient.decease_note or 'No note provided',
        ])
    if len(deceased_data) > 1:
        deceased_table = Table(deceased_data, colWidths=[6*cm, 4*cm, 7*cm])
        deceased_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
        ]))
        elements.append(deceased_table)
    else:
        elements.append(Paragraph("No deaths recorded.", normal_style))
    elements.append(Spacer(1, 0.3*cm))

    elements.append(Paragraph("Mortality Totals", subtitle_style))
    elements.append(Paragraph(f"Total Deaths: {context['total_deaths']}", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

@login_required
def center_detail(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if not is_viewer(request.user):
        return HttpResponse("Permission denied.", status=403)
    return render(request, 'centers/center_detail.html', {
        'center': center,
        'technical_staff': center.technical_staff.all(),
        'medical_staff': center.medical_staff.all(),
        'paramedical_staff': center.paramedical_staff.all(),
        'administrative_staff': center.administrative_staff.all(),
        'worker_staff': center.worker_staff.all(),
        'patients': center.patient_staff.all(),
    })


#=====================================APIS===================================

@method_decorator(csrf_exempt, name='dispatch')
class CenterLoginAPIView(APIView):
    def get_tokens_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        refresh['is_superuser'] = user.is_superuser
        refresh['username'] = user.username
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

    def post(self, request):
        logger.debug("Received POST request to CenterLoginAPIView. CSRF exempt: %s", request.META.get('CSRF_COOKIE') is None)
        
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for API login request")
            return Response({"error": "Invalid center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            logger.warning("Missing username or password in API login request")
            return Response({"error": "Username and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=username, password=password)
        if user is None:
            logger.warning("Failed login attempt for username: %s at center %s", username, tenant.label)
            return Response({"error": "Invalid username or password."}, status=status.HTTP_401_UNAUTHORIZED)

        if user.is_superuser:
            logger.info("Superadmin %s logging in to center %s", username, tenant.label)
            try:
                profile = UserProfile.objects.get(user=user)
                tokens = self.get_tokens_for_user(user)
                logger.info("Superadmin %s logged in for center %s as LOCAL_ADMIN", username, tenant.label)
                return Response({
                    "access": tokens["access"],
                    "refresh": tokens["refresh"],
                    "role": "LOCAL_ADMIN",
                    "center": tenant.label
                }, status=status.HTTP_200_OK)
            except UserProfile.DoesNotExist:
                logger.error("No verification profile for superadmin %s", username)
                return Response({"error": "Verification profile missing. Contact support."}, status=status.HTTP_403_FORBIDDEN)

        staff_types = [AdministrativeStaff, ParamedicalStaff, TechnicalStaff, MedicalStaff, WorkerStaff]
        staff = None
        staff_role = None
        for staff_type in staff_types:
            try:
                staff = staff_type.objects.get(user=user, center=tenant)
                staff_role = staff.role
                logger.debug("Found %s for user %s in center %s", staff_type.__name__, username, tenant.label)
                break
            except staff_type.DoesNotExist:
                logger.debug("No %s found for user %s in center %s", staff_type.__name__, username, tenant.label)
                continue

        if staff:
            try:
                profile = UserProfile.objects.get(user=user)
                if not profile.is_verified:
                    logger.info("User %s requires email verification for center %s", username, tenant.label)
                    return Response({
                        "error": "Email verification required.",
                        "redirect_to": "/verify-email",
                        "user_id": user.id
                    }, status=status.HTTP_403_FORBIDDEN)
                tokens = self.get_tokens_for_user(user)
                logger.info("User %s logged in for center %s as %s", username, tenant.label, staff.__class__.__name__)
                return Response({
                    "access": tokens["access"],
                    "refresh": tokens["refresh"],
                    "role": staff_role,
                    "center": tenant.label,
                    "is_verified": profile.is_verified,
                    "has_role_privileges": profile.has_role_privileges()
                }, status=status.HTTP_200_OK)
            except UserProfile.DoesNotExist:
                logger.error("No verification profile for user %s", username)
                return Response({"error": "Verification profile missing. Contact support."}, status=status.HTTP_403_FORBIDDEN)
        else:
            logger.warning("User %s not authorized for center %s", username, tenant.label)
            return Response({"error": "You are not authorized for this center."}, status=status.HTTP_403_FORBIDDEN)

@method_decorator(csrf_exempt, name='dispatch')
class AddAdministrativeStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def post(self, request):
        logger.debug("Received POST request to AddAdministrativeStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add administrative staff request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response(
                {"error": "Permission denied. Only local admins can add staff."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id  # Set center for form validation

        # Validate and save form
        form = AdministrativeStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("Administrative staff %s %s (ID: %s) added by %s in center %s",
                               staff.nom, staff.prenom, staff.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Administrative staff added successfully.",
                            "staff_id": staff.id,
                            "user_id": staff.user.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("Error saving administrative staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Administrative staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
@method_decorator(csrf_exempt, name='dispatch')
class AddTechnicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def post(self, request):
        logger.debug("Received POST request to AddTechnicalStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add technical staff request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response(
                {"error": "Permission denied. Only local admins can add staff."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id

        # Validate and save form
        form = TechnicalStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("Technical staff %s %s (ID: %s) added by %s in center %s",
                               staff.nom, staff.prenom, staff.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Technical staff added successfully.",
                            "staff_id": staff.id,
                            "user_id": staff.user.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("Error saving technical staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Technical staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

@method_decorator(csrf_exempt, name='dispatch')
class AddMedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def post(self, request):
        logger.debug("MEDICAL_STAFF: Received POST request to AddMedicalStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MEDICAL_STAFF: No tenant found for add medical staff request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id

        # Validate and save form
        form = MedicalStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("MEDICAL_STAFF: Medical staff %s %s (ID: %s) added by %s in center %s",
                                staff.nom, staff.prenom, staff.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Medical staff added successfully.",
                            "staff_id": staff.id,
                            "user_id": staff.user.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("MEDICAL_STAFF: Error saving medical staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("MEDICAL_STAFF: Medical staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

@method_decorator(csrf_exempt, name='dispatch')
class AddParamedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def post(self, request):
        logger.debug("PARAMEDICAL_STAFF: Received POST request to AddParamedicalStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("PARAMEDICAL_STAFF: No tenant found for add paramedical staff request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id

        # Validate and save form
        form = ParamedicalStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("PARAMEDICAL_STAFF: Paramedical staff %s %s (ID: %s) added by %s in center %s",
                                staff.nom, staff.prenom, staff.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Paramedical staff added successfully.",
                            "staff_id": staff.id,
                            "user_id": staff.user.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("PARAMEDICAL_STAFF: Error saving paramedical staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("PARAMEDICAL_STAFF: Paramedical staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

@method_decorator(csrf_exempt, name='dispatch')
class AddWorkerStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def post(self, request):
        logger.debug("WORKER_STAFF: Received POST request to AddWorkerStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("WORKER_STAFF: No tenant found for add worker staff request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id

        # Validate and save form
        form = WorkerStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("WORKER_STAFF: Worker staff %s %s (ID: %s) added by %s in center %s",
                                staff.nom, staff.prenom, staff.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Worker staff added successfully.",
                            "staff_id": staff.id,
                            "user_id": staff.user.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("WORKER_STAFF: Error saving worker staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("WORKER_STAFF: Worker staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
@method_decorator(csrf_exempt, name='dispatch')
class AddPatientAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']
    read_only_roles = ['VIEWER']

    def post(self, request):
        logger.debug("Received POST request to AddPatientAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add patient request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id

        # Validate and save form
        form = PatientForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    patient = form.save(commit=True)
                    logger.info("Patient %s %s (ID: %s) added by %s in center %s",
                               patient.nom, patient.prenom, patient.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Patient added successfully.",
                            "patient_id": patient.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("Error saving patient: %s", str(e))
                return Response(
                    {"error": f"Failed to save patient: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Patient form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    def get(self, request):
        logger.debug("Received GET request to AddPatientAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for patient list request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            patients = Patient.objects.filter(center=tenant)
            data = [{
                'id': p.id,
                'nom': p.nom,
                'prenom': p.prenom,
                'cin': p.cin,
                'status': p.status
            } for p in patients]
            logger.info("Patient list retrieved by %s in center %s", request.user.username, tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching patients: %s", str(e))
            return Response(
                {"error": f"Failed to fetch patients: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
@method_decorator(csrf_exempt, name='dispatch')
class DeclareDeceasedAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request, patient_id):
        logger.debug("Received POST request to DeclareDeceasedAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for declare deceased request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response(
                {"error": "Permission denied. Only local admins can declare patients deceased."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check if patient exists and belongs to the center
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response(
                {"error": "Patient not found or does not belong to this center."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Validate form
        form_data = request.data.copy()
        form = DeceasePatientForm(form_data, instance=patient)
        if form.is_valid():
            try:
                with transaction.atomic():
                    patient = form.save(commit=False)
                    patient.is_deceased = True
                    patient.save()
                    logger.info("Patient %s %s (ID: %s) declared deceased by %s in center %s",
                               patient.nom, patient.prenom, patient.id, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Patient declared deceased.",
                            "patient_id": patient.id
                        },
                        status=status.HTTP_200_OK
                    )
            except Exception as e:
                logger.error("Error declaring patient deceased: %s", str(e))
                return Response(
                    {"error": f"Failed to declare patient deceased: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Decease patient form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )
@method_decorator(csrf_exempt, name='dispatch')
class AddHemodialysisSessionAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddHemodialysisSessionAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add hemodialysis session request")
            return Response(
                {"error": "Invalid or missing center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response(
                {"error": "Permission denied. Only local admins can add hemodialysis sessions."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check if patient and medical activity exist
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            medical_activity = MedicalActivity.objects.get(patient=patient, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response(
                {"error": "Patient not found or does not belong to this center."},
                status=status.HTTP_404_NOT_FOUND
            )
        except MedicalActivity.DoesNotExist:
            logger.error("Medical activity not found for patient ID %s in center %s", patient_id, tenant.label)
            return Response(
                {"error": "Medical activity not found for this patient."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Prepare form data
        form_data = request.data.copy()

        # Validate and save form
        form = HemodialysisSessionForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    session = form.save(commit=False)
                    session.medical_activity = medical_activity
                    session.center = tenant
                    session.save()
                    logger.info("Hemodialysis session (ID: %s) added for patient %s %s by %s in center %s",
                               session.id, patient.nom, patient.prenom, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Hemodialysis session added successfully.",
                            "session_id": session.id,
                            "patient_id": patient_id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("Error saving hemodialysis session: %s", str(e))
                return Response(
                    {"error": f"Failed to save hemodialysis session: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Hemodialysis session form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

@method_decorator(csrf_exempt, name='dispatch')
class AddTransmittableDiseaseRefAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request):
        logger.debug("TRANS_REF: Received POST request to AddTransmittableDiseaseRefAPIView. User: %s, Data: %s",
                    request.user.username, request.data)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("TRANS_REF: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("TRANS_REF: Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can add transmittable disease references."}, status=status.HTTP_403_FORBIDDEN)

        # Validate and save form
        form = TransmittableDiseaseRefForm(request.data)
        if form.is_valid():
            try:
                with transaction.atomic():
                    disease_ref = form.save()
                    logger.info("TRANS_REF: Transmittable disease ref (ID: %s, Label: %s) added by %s in center %s",
                               disease_ref.id, disease_ref.label_disease, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Transmittable disease reference added successfully.",
                            "disease_ref_id": disease_ref.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("TRANS_REF: Error saving transmittable disease ref: %s", str(e))
                return Response({"error": f"Failed to save transmittable disease ref: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("TRANS_REF: Transmittable disease ref form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)

class UpdateMachineAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    required_roles = ['ADMINISTRATIVE', 'MEDICAL']

    def get(self, request, machine_id):
        tenant = request.tenant
        if not tenant:
            logger.error("No tenant provided for UpdateMachineAPIView GET")
            return Response({"error": "No center found for this subdomain."}, status=status.HTTP_404_NOT_FOUND)

        try:
            machine = Machine.objects.get(id=machine_id, center=tenant)
            return Response({
                "machine": {
                    "id": machine.id,
                    "brand": machine.brand,
                    "functional": machine.functional,
                    "reserve": machine.reserve,
                    "refurbished": machine.refurbished,
                    "nbre_hrs": machine.nbre_hrs,
                    "membrane": {"id": machine.membrane.id, "type": machine.membrane.type} if machine.membrane else None,
                    "filtre": {"id": machine.filtre.id, "type": machine.filtre.type, "sterilisation": machine.filtre.sterilisation} if machine.filtre else None,
                    "center": machine.center.label
                }
            }, status=status.HTTP_200_OK)
        except ObjectDoesNotExist:
            logger.error("Machine %s not found for center %s", machine_id, tenant.label)
            return Response({"error": "Machine not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("Failed to fetch machine %s for center %s: %s", machine_id, tenant.label, str(e))
            return Response({"error": "Failed to fetch machine."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request, machine_id):
        tenant = request.tenant
        if not tenant:
            logger.error("No tenant provided for UpdateMachineAPIView PUT")
            return Response({"error": "No center found for this subdomain."}, status=status.HTTP_404_NOT_FOUND)

        try:
            machine = Machine.objects.get(id=machine_id, center=tenant)
        except ObjectDoesNotExist:
            logger.error("Machine %s not found for center %s", machine_id, tenant.label)
            return Response({"error": "Machine not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data

        # Update simple fields
        machine.brand = data.get('brand', machine.brand)
        machine.functional = data.get('functional', machine.functional)
        machine.reserve = data.get('reserve', machine.reserve)
        machine.refurbished = data.get('refurbished', machine.refurbished)
        machine.nbre_hrs = data.get('nbre_hrs', machine.nbre_hrs)

        # Update foreign keys if provided
        if 'membrane_id' in data:
            try:
                membrane = Membrane.objects.get(id=data['membrane_id'])
                machine.membrane = membrane
            except ObjectDoesNotExist:
                logger.error("Membrane %s not found", data['membrane_id'])
                return Response({"error": "Membrane not found."}, status=status.HTTP_400_BAD_REQUEST)

        if 'filtre_id' in data:
            try:
                filtre = Filtre.objects.get(id=data['filtre_id'])
                machine.filtre = filtre
            except ObjectDoesNotExist:
                logger.error("Filtre %s not found", data['filtre_id'])
                return Response({"error": "Filtre not found."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            machine.save()
            logger.info("Machine %s updated successfully for center %s", machine_id, tenant.label)
            return Response({
                "message": "Machine updated successfully.",
                "machine": {
                    "id": machine.id,
                    "brand": machine.brand,
                    "functional": machine.functional,
                    "reserve": machine.reserve,
                    "refurbished": machine.refurbished,
                    "nbre_hrs": machine.nbre_hrs,
                    "membrane": str(machine.membrane),
                    "filtre": str(machine.filtre),
                    "center": machine.center.label
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Failed to update machine %s for center %s: %s", machine_id, tenant.label, str(e))
            return Response({"error": "Failed to update machine."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
class DeleteMachineAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    required_roles = ['LOCAL_ADMIN','TECHNICAL']

    def delete(self, request, machine_id):
        tenant = request.tenant
        if not tenant:
            logger.error("No tenant provided for DeleteMachineAPIView")
            return Response({"error": "No center found for this subdomain."}, status=status.HTTP_404_NOT_FOUND)

        try:
            machine = Machine.objects.get(id=machine_id, center=tenant)
        except ObjectDoesNotExist:
            logger.error("Machine %s not found for center %s", machine_id, tenant.label)
            return Response({"error": "Machine not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            machine.delete()
            logger.info("Machine %s deleted successfully for center %s", machine_id, tenant.label)
            return Response({"message": "Machine deleted successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Failed to delete machine %s for center %s: %s", machine_id, tenant.label, str(e))
            return Response({"error": "Failed to delete machine."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class AddComplicationsRefAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request):
        logger.debug("COMP_REF: Received POST request to AddComplicationsRefAPIView. User: %s, Data: %s",
                    request.user.username, request.data)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("COMP_REF: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("COMP_REF: Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can add complications references."}, status=status.HTTP_403_FORBIDDEN)

        # Validate and save form
        form = ComplicationsRefForm(request.data)
        if form.is_valid():
            try:
                with transaction.atomic():
                    complication_ref = form.save()
                    logger.info("COMP_REF: Complication ref (ID: %s, Label: %s) added by %s in center %s",
                               complication_ref.id, complication_ref.label_complication, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Complication reference added successfully.",
                            "complication_ref_id": complication_ref.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("COMP_REF: Error saving complication ref: %s", str(e))
                return Response({"error": f"Failed to save complication ref: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("COMP_REF: Complication ref form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class AddTransplantationRefAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request):
        logger.debug("TRANSPLANT_REF: Received POST request to AddTransplantationRefAPIView. User: %s, Data: %s",
                    request.user.username, request.data)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("TRANSPLANT_REF: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("TRANSPLANT_REF: Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can add transplantation references."}, status=status.HTTP_403_FORBIDDEN)

        # Validate and save form
        form = TransplantationRefForm(request.data)
        if form.is_valid():
            try:
                with transaction.atomic():
                    transplantation_ref = form.save()
                    logger.info("TRANSPLANT_REF: Transplantation ref (ID: %s, Label: %s) added by %s in center %s",
                               transplantation_ref.id, transplantation_ref.label_transplantation, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Transplantation reference added successfully.",
                            "transplantation_ref_id": transplantation_ref.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("TRANSPLANT_REF: Error saving transplantation ref: %s", str(e))
                return Response({"error": f"Failed to save transplantation ref: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("TRANSPLANT_REF: Transplantation ref form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)
        

@method_decorator(csrf_exempt, name='dispatch')
class AddMachineAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'TECHNICAL']
    read_only_roles = ['VIEWER']

    def post(self, request):
        logger.debug("MACHINE: Received POST request to AddMachineAPIView. User: %s, Data: %s",
                    request.user.username, request.data)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MACHINE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        # Prepare form data
        form_data = request.data.copy()
        form_data['center'] = tenant.id

        # Validate and save form
        form = MachineForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    machine = form.save(commit=True)
                    logger.info("MACHINE: Machine (ID: %s, Brand: %s) added by %s in center %s",
                               machine.id, machine.brand, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Machine added successfully.",
                            "machine_id": machine.id,
                            "brand": machine.brand
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("MACHINE: Error saving machine: %s", str(e))
                return Response({"error": f"Failed to save machine: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("MACHINE: Machine form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        logger.debug("MACHINE: Received GET request to AddMachineAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MACHINE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            machines = Machine.objects.filter(center=tenant)
            data = [
                {
                    "id": machine.id,
                    "brand": machine.brand,
                    "functional": machine.functional,
                    "reserve": machine.reserve,
                    "refurbished": machine.refurbished,
                    "nbre_hrs": machine.nbre_hrs,
                    "membrane": {
                        "id": machine.membrane.id,
                        "type": machine.membrane.type
                    } if machine.membrane else None,
                    "filtre": {
                        "id": machine.filtre.id,
                        "type": machine.filtre.type,
                        "sterilisation": machine.filtre.sterilisation
                    } if machine.filtre else None
                } for machine in machines
            ]
            logger.info("MACHINE: Machine list retrieved by %s in center %s", request.user.username, tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("MACHINE: Error fetching machines: %s", str(e))
            return Response({"error": f"Failed to fetch machines: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        
class UserProfileView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        # Map role choices to display names
        role_display_map = {
            'LOCAL_ADMIN': 'Center Admin',
            'SUBMITTER': 'Submitter',
            'MEDICAL_PARA_STAFF': 'Medical & Paramedical Staff',
            'VIEWER': 'Viewer',
        }

        # Check each staff profile type
        try:
            if hasattr(user, 'administrative_profile') and user.administrative_profile:
                staff = user.administrative_profile
            elif hasattr(user, 'medical_profile') and user.medical_profile:
                staff = user.medical_profile
            elif hasattr(user, 'paramedical_profile') and user.paramedical_profile:
                staff = user.paramedical_profile
            elif hasattr(user, 'technical_profile') and user.technical_profile:
                staff = user.technical_profile
            elif hasattr(user, 'worker_profile') and user.worker_profile:
                staff = user.worker_profile
            else:
                return Response({
                    'error': 'No staff profile found for this user.'
                }, status=404)

            # Verify center matches tenant
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            if staff.center != center:
                return Response({
                    'error': 'Staff not associated with this center.'
                }, status=403)

            return Response({
                'first_name': staff.prenom,
                'last_name': staff.nom,
                'role': role_display_map.get(staff.role, 'Unknown')
            })
        except ObjectDoesNotExist:
            return Response({
                'error': 'Center not found for this tenant.'
            }, status=404)
        

class PatientsView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            patients = Patient.objects.filter(center=center).select_related('cnam').values(
                'id', 'nom', 'prenom', 'cin', 'weight', 'age', 'cnam__number', 'status',
                'entry_date', 'previously_dialysed', 'date_first_dia', 'blood_type', 'gender','hypertension', 'diabetes', 'decease_note'
            )
            return Response(list(patients))
        except ObjectDoesNotExist:
            return Response({
                'error': 'Center not found for this tenant.'
            }, status=404)

class PatientMedicalActivityView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request, patient_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            patient = Patient.objects.get(id=patient_id, center=center)
            activity = patient.medical_activity
            return Response({
                'id': activity.id,
                'created_at': activity.created_at,
            })
        except ObjectDoesNotExist:
            return Response({
                'error': 'Patient, medical activity, or center not found.'
            }, status=404)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import transaction
from centers.models import Center, AdministrativeStaff, MedicalStaff, Patient, MedicalActivity, HemodialysisSession, TransmittableDisease, Complications, Transplantation
from centers.forms import DeceasePatientForm, HemodialysisSessionForm, TransmittableDiseaseForm, ComplicationsForm, TransplantationForm
import logging
from rest_framework import status

logger = logging.getLogger(__name__)

def is_local_admin(user):
    return hasattr(user, 'administrative_profile') and user.administrative_profile.role == 'LOCAL_ADMIN'

def is_viewer(user):
    return hasattr(user, 'administrative_profile') or hasattr(user, 'medical_profile') or hasattr(user, 'paramedical_profile') or hasattr(user, 'technical_profile') or hasattr(user, 'worker_profile')

def is_submitter(user):
    return hasattr(user, 'administrative_profile') and user.administrative_profile.role in ['SUBMITTER', 'LOCAL_ADMIN']

class UserProfileView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        role_display_map = {
            'LOCAL_ADMIN': 'Center Admin',
            'SUBMITTER': 'Submitter',
            'MEDICAL_PARA_STAFF': 'Medical & Paramedical Staff',
            'VIEWER': 'Viewer',
        }

        try:
            if hasattr(user, 'administrative_profile') and user.administrative_profile:
                staff = user.administrative_profile
            elif hasattr(user, 'medical_profile') and user.medical_profile:
                staff = user.medical_profile
            elif hasattr(user, 'paramedical_profile') and user.paramedical_profile:
                staff = user.paramedical_profile
            elif hasattr(user, 'technical_profile') and user.technical_profile:
                staff = user.technical_profile
            elif hasattr(user, 'worker_profile') and user.worker_profile:
                staff = user.worker_profile
            else:
                return Response({
                    'error': 'No staff profile found for this user.'
                }, status=404)

            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            if staff.center != center:
                return Response({
                    'error': 'Staff not associated with this center.'
                }, status=403)

            return Response({
                'first_name': staff.prenom,
                'last_name': staff.nom,
                'role': role_display_map.get(staff.role, 'Unknown'),
                'raw_role': staff.role
            })
        except ObjectDoesNotExist:
            return Response({
                'error': 'Center not found for this tenant.'
            }, status=404)


class PatientDetailAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request, patient_id):
        logger.debug("PATIENT_DETAIL: Received GET request to PatientDetailAPIView. User: %s, Patient ID: %s",
                     request.user.username, patient_id)

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("PATIENT_DETAIL: No tenant found for center")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            hemodialysis_sessions = HemodialysisSession.objects.filter(medical_activity__patient=patient).values(
                'id',
                'type__name',
                'method__name',
                'date_of_session',
                'responsible_doc__nom',
                'responsible_doc__prenom',
                'pre_dialysis_bp',
                'during_dialysis_bp',
                'post_dialysis_bp',
                'heart_rate',
                'creatinine',
                'urea',
                'potassium',
                'hemoglobin',
                'hematocrit',
                'albumin',
                'kt_v',
                'urine_output',
                'dry_weight',
                'fluid_removal_rate',
                'dialysis_duration',
                'vascular_access_type',
                'dialyzer_type',
                'severity_of_case'
            )
            diseases = TransmittableDisease.objects.filter(medical_activity__patient=patient).values(
                'id', 'disease__label_disease', 'date_of_contraction'
            )
            complications = Complications.objects.filter(medical_activity__patient=patient).values(
                'id', 'complication__label_complication', 'notes', 'date_of_contraction'
            )
            transplantations = Transplantation.objects.filter(medical_activity__patient=patient).values(
                'id', 'transplantation__label_transplantation', 'date_operation', 'notes'
            )
            logger.info("PATIENT_DETAIL: Patient ID %s fetched by %s for center %s", patient_id, request.user.username, tenant.label)
            return Response({
                'id': patient.id,
                'nom': patient.nom,
                'prenom': patient.prenom,
                'cin': patient.cin,
                'weight': patient.weight,
                'age': patient.age,
                'cnam__number': patient.cnam.number,
                'status': patient.status,
                'decease_note': patient.decease_note,
                'entry_date': patient.entry_date,
                'previously_dialysed': patient.previously_dialysed,
                'date_first_dialysis': patient.date_first_dia,
                'blood_type': patient.blood_type,
                'gender': patient.gender,
                'diabetes':patient.diabetes,
                'hypertension':patient.hypertension,
                'hemodialysis_sessions': list(hemodialysis_sessions),
                'transmittable_diseases': list(diseases),
                'complications': list(complications),
                'transplantations': list(transplantations),
            }, status=status.HTTP_200_OK)
        except Patient.DoesNotExist:
            logger.error("PATIENT_DETAIL: Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=status.HTTP_404_NOT_FOUND)

@method_decorator(csrf_exempt, name='dispatch')
class DeclareDeceasedAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request, patient_id):
        logger.debug("DECEASE: Received POST request to DeclareDeceasedAPIView for patient ID: %s. User: %s",
                     patient_id, request.user.username)

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("DECEASE: No tenant found for declare deceased request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("DECEASE: Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=status.HTTP_404_NOT_FOUND)

        form_data = request.data.copy()
        form = DeceasePatientForm(form_data, instance=patient)
        if form.is_valid():
            try:
                with transaction.atomic():
                    patient = form.save(commit=False)
                    patient.status = 'DECEASED'
                    patient.save()
                    logger.info("DECEASE: Patient %s %s (ID: %s) declared deceased by %s in center %s",
                                patient.nom, patient.prenom, patient.id, request.user.username, tenant.label)
                    return Response({"success": "Patient declared deceased.", "patient_id": patient.id}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error("DECEASE: Error declaring patient deceased: %s", str(e))
                return Response({"error": f"Failed to declare patient deceased: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("DECEASE: Decease patient form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)

class PatientMedicalActivityView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request, patient_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            patient = Patient.objects.get(id=patient_id, center=center)
            activity = patient.medical_activity
            return Response({
                'id': activity.id,
                'created_at': activity.created_at,
            })
        except ObjectDoesNotExist:
            return Response({
                'error': 'Patient, medical activity, or center not found.'
            }, status=404)

@method_decorator(csrf_exempt, name='dispatch')
class AddHemodialysisSessionAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']
    read_only_roles = ['VIEWER']

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddHemodialysisSessionAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add hemodialysis session request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, 'unknown')
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        form_data = request.data.copy()
        form_data['center'] = tenant.id
        form = HemodialysisSessionForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    session = form.save(commit=False)
                    try:
                        medical_activity = MedicalActivity.objects.get(patient=patient)
                    except MedicalActivity.DoesNotExist:
                        logger.info("Creating new MedicalActivity for patient %s %s (ID: %s)",
                                    patient.nom, patient.prenom, patient.id)
                        medical_activity = MedicalActivity.objects.create(
                            patient=patient,
                            created_at=patient.entry_date
                        )
                    session.medical_activity = medical_activity
                    session.save()
                    logger.info("Hemodialysis session (ID: %s) added for patient %s %s by %s in center %s",
                               session.id, patient.nom, patient.prenom, request.user.username, tenant.label)
                    return Response({
                        "success": "Hemodialysis session added successfully.",
                        "session_id": session.id,
                        "patient_id": patient.id,
                        "type": session.type.id if session.type else None,
                        "method": session.method.id if session.method else None,
                        "date_of_session": session.date_of_session,
                        "responsible_doc": session.responsible_doc.id if session.responsible_doc else None,
                        "pre_dialysis_bp": session.pre_dialysis_bp,
                        "during_dialysis_bp": session.during_dialysis_bp,
                        "post_dialysis_bp": session.post_dialysis_bp,
                        "heart_rate": session.heart_rate
                    }, status=201)
            except Exception as e:
                logger.error("Error saving hemodialysis session for patient ID %s: %s", patient_id, str(e))
                return Response({"error": f"Failed to save hemodialysis session: {str(e)}"}, status=400)
        else:
            logger.warning("Hemodialysis session form invalid for patient ID %s: %s", patient_id, form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=400)

    def get(self, request, patient_id):
        logger.debug("Received GET request to AddHemodialysisSessionAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for hemodialysis session list request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            sessions = HemodialysisSession.objects.filter(medical_activity__patient=patient)
            data = [
                {
                    "id": s.id,
                    "type": s.type.name if s.type else None,
                    "method": s.method.name if s.method else None,
                    "date_of_session": s.date_of_session,
                    "responsible_doc": f"{s.responsible_doc.nom} {s.responsible_doc.prenom}" if s.responsible_doc else None,
                    "pre_dialysis_bp": s.pre_dialysis_bp,
                    "during_dialysis_bp": s.during_dialysis_bp,
                    "post_dialysis_bp": s.post_dialysis_bp,
                    "heart_rate": s.heart_rate
                } for s in sessions
            ]
            logger.info("Hemodialysis session list retrieved for patient %s %s (ID: %s) by %s in center %s",
                       patient.nom, patient.prenom, patient.id, request.user.username, tenant.label)
            return Response(data, status=200)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, 'unknown')
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        except Exception as e:
            logger.error("Error fetching sessions: %s", str(e))
            return Response({"error": f"Failed to fetch sessions: {str(e)}"}, status=400)

@method_decorator(csrf_exempt, name='dispatch')
class AddTransmittableDiseaseAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']
    read_only_roles = ['VIEWER']

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddTransmittableDiseaseAPIView for patient ID: %s. User: %s",
                     patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add transmittable disease request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        
        form_data = request.data.copy()
        form = TransmittableDiseaseForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    disease = form.save(commit=False)
                    if form.cleaned_data.get('new_disease_name'):
                        ref_form_data = {
                            'label_disease': form.cleaned_data['new_disease_name'],
                            'type_of_transmission': form_data.get('type_of_transmission', 'Unknown')
                        }
                        ref_form = TransmittedDiseaseRefForm(ref_form_data)
                        if ref_form.is_valid():
                            disease_ref = ref_form.save()
                            disease.disease = disease_ref
                        else:
                            logger.warning("TransmittableDiseaseRef form invalid: %s", ref_form.errors)
                            return Response({"error": "Invalid new disease name.", "errors": ref_form.errors.as_data()}, status=400)
                    try:
                        disease.medical_activity = patient.medical_activity
                    except AttributeError:
                        disease.medical_activity = MedicalActivity.objects.create(patient=patient, created_at=patient.entry_date)
                    disease.save()
                    logger.info("Transmittable disease (ID: %s) added for patient %s %s by %s in center %s",
                                    disease.id, patient.nom, patient.prenom, patient.id, request.user.username, tenant.label)
                    return Response({
                        "success": "Transmittable disease added successfully.",
                        "disease_id": disease.id,
                        "patient_id": patient_id
                    }, status=201)
            except Exception as e:
                logger.error("Error saving transmittable disease: %s", str(e))
                return Response({"error": f"Failed to save transmittable disease: {str(e)}"}, status=400)
        else:
            logger.warning("Transmittable disease form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=400)

    def get(self, request, patient_id):
        logger.debug("Received GET request to AddTransmittableDiseaseAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for transmittable disease list request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            diseases = TransmittableDisease.objects.filter(medical_activity__patient=patient)
            data = [
                {
                    "id": d.id,
                    "disease": d.disease.label_disease if d.disease else None,
                    "date_added": d.date_added
                } for d in diseases
            ]
            logger.info("Transmittable disease list retrieved for patient %s by %s in center %s",
                       patient.id, request.user.username, tenant.label)
            return Response(data, status=200)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        except Exception as e:
            logger.error("Error fetching diseases: %s", str(e))
            return Response({"error": f"Failed to fetch diseases: {str(e)}"}, status=400)

@method_decorator(csrf_exempt, name='dispatch')
class AddComplicationsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']
    read_only_roles = ['VIEWER']

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddComplicationsAPIView for patient ID: %s. User: %s",
                     patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add complications request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        
        form_data = request.data.copy()
        form = ComplicationsForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    complication = form.save(commit=False)
                    if form.cleaned_data.get('new_complication_name'):
                        ref_form = ComplicationsRefForm({'label_complication': form.cleaned_data['new_complication_name']})
                        if ref_form.is_valid():
                            complication_ref = ref_form.save()
                            complication.complication = complication_ref
                        else:
                            logger.warning("ComplicationsRef form invalid: %s", ref_form.errors)
                            return Response({"error": "Invalid new complication name.", "errors": ref_form.errors.as_data()}, status=400)
                    try:
                        complication.medical_activity = patient.medical_activity
                    except AttributeError:
                        complication.medical_activity = MedicalActivity.objects.create(patient=patient, created_at=patient.entry_date)
                    complication.save()
                    logger.info("Complication (ID: %s) added for patient %s %s by %s in center %s",
                               complication.id, patient.nom, patient.prenom, request.user.username, tenant.label)
                    return Response({
                        "success": "Complication added successfully.",
                        "complication_id": complication.id,
                        "patient_id": patient_id
                    }, status=201)
            except Exception as e:
                logger.error("Error saving complication: %s", str(e))
                return Response({"error": f"Failed to save complication: {str(e)}"}, status=400)
        else:
            logger.warning("Complications form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=400)

    def get(self, request, patient_id):
        logger.debug("Received GET request to AddComplicationsAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for complications list request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            complications = Complications.objects.filter(medical_activity__patient=patient)
            data = [
                {
                    "id": c.id,
                    "complication": c.complication.label_complication if c.complication else None,
                    "date_added": c.date_added
                } for c in complications
            ]
            logger.info("Complications list retrieved for patient %s by %s in center %s",
                       patient.id, request.user.username, tenant.label)
            return Response(data, status=200)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        except Exception as e:
            logger.error("Error fetching complications: %s", str(e))
            return Response({"error": f"Failed to fetch complications: {str(e)}"}, status=400)

@method_decorator(csrf_exempt, name='dispatch')
class AddTransplantationAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddTransplantationAPIView for patient ID: %s. User: %s",
                     patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add transplantation request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        
        form_data = request.data.copy()
        form = TransplantationForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    transplantation = form.save(commit=False)
                    if form.cleaned_data.get('new_transplantation_name'):
                        ref_form = TransplantationRefForm({'label_transplantation': form.cleaned_data['new_transplantation_name']})
                        if ref_form.is_valid():
                            transplantation_ref = ref_form.save()
                            transplantation.transplantation = transplantation_ref
                        else:
                            logger.warning("TransplantationRef form invalid: %s", ref_form.errors)
                            return Response({"error": "Invalid new transplantation name.", "errors": ref_form.errors.as_data()}, status=400)
                    try:
                        transplantation.medical_activity = patient.medical_activity
                    except AttributeError:
                        transplantation.medical_activity = MedicalActivity.objects.create(patient=patient, created_at=patient.entry_date)
                    transplantation.save()
                    logger.info("Transplantation (ID: %s) added for patient %s %s by %s in center %s",
                               transplantation.id, patient.nom, patient.prenom, request.user.username, tenant.label)
                    return Response({
                        "success": "Transplantation added successfully.",
                        "transplantation_id": transplantation.id,
                        "patient_id": patient_id
                    }, status=201)
            except Exception as e:
                logger.error("Error saving transplantation: %s", str(e))
                return Response({"error": f"Failed to save transplantation: {str(e)}"}, status=400)
        else:
            logger.warning("Transplantation form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=400)

    def get(self, request, patient_id):
        logger.debug("Received GET request to AddTransplantationAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for transplantation list request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            transplantations = Transplantation.objects.filter(medical_activity__patient=patient)
            data = [
                {
                    "id": t.id,
                    "transplantation": t.transplantation.label_transplantation if t.transplantation else None,
                    "date_added": t.date_added
                } for t in transplantations
            ]
            logger.info("Transplantation list retrieved for patient %s by %s in center %s",
                       patient.id, request.user.username, tenant.label)
            return Response(data, status=200)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        except Exception as e:
            logger.error("Error fetching transplantations: %s", str(e))
            return Response({"error": f"Failed to fetch transplantations: {str(e)}"}, status=400)

class MedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            medical_staff = MedicalStaff.objects.filter(center=center).values(
                'id', 'nom', 'prenom', 'cin', 'role', 'cnom'
            )
            return Response(list(medical_staff))
        except ObjectDoesNotExist:
            logger.error("Center not found for tenant %s", request.tenant.sub_domain)
            return Response({
                'error': 'Center not found for this tenant.'
            }, status=404)
        
class TypeHemoAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        type_hemos = TypeHemo.objects.all().values('id', 'name')
        return Response(list(type_hemos))

class MethodHemoAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        type_hemo_id = request.query_params.get('type_hemo_id')
        queryset = MethodHemo.objects.all()
        if type_hemo_id:
            try:
                queryset = queryset.filter(type_hemo_id=int(type_hemo_id))
            except ValueError:
                return Response({"error": "Invalid type_hemo_id."}, status=400)
        method_hemos = queryset.values('id', 'name', 'type_hemo_id')
        return Response(list(method_hemos))
    

class TransmittableDiseaseRefAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        diseases = TransmittableDiseaseRef.objects.all().values('id', 'label_disease', 'type_of_transmission')
        return Response(list(diseases))

class ComplicationsRefAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        complications = ComplicationsRef.objects.all().values('id', 'label_complication')
        return Response(list(complications))

class TransplantationRefAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']

    def get(self, request):
        transplantations = TransplantationRef.objects.all().values('id', 'label_transplantation')
        return Response(list(transplantations))
    

@method_decorator(csrf_exempt, name='dispatch')
class CNAMListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF']
    def get(self, request):
        logger.debug("Received GET request to CNAMListAPIView. User: %s", request.user.username)
        try:
            cnams = CNAM.objects.all()
            data = [{'id': cnam.id, 'number': cnam.number} for cnam in cnams]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching CNAM records: %s", str(e))
            return Response({"error": f"Failed to fetch CNAM records: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class AdministrativeStaffListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def get(self, request):
        logger.debug("Received GET request to AdministrativeStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list administrative staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = AdministrativeStaff.objects.filter(center=tenant)
            staff_data = [
                {
                    'user_id': s.user.id,
                    'class_id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'job_title': s.job_title,
                    'email': s.user.email,
                    'admin_accord': UserProfile.objects.filter(user=s.user).first().admin_accord
                        if UserProfile.objects.filter(user=s.user).exists() else False
                } for s in staff
            ]
            logger.info("Fetched %d administrative staff for center %s", len(staff_data), tenant.label)
            return Response(staff_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching administrative staff: %s", str(e))
            return Response({"error": f"Failed to fetch administrative staff: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class MedicalStaffListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN','MEDICAL_PARA_STAFF']

    def get(self, request):
        logger.debug("Received GET request to MedicalStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list medical staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = MedicalStaff.objects.filter(center=tenant)
            staff_data = [
                {
                    'user_id': s.user.id,
                    'class_id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'cnom': s.cnom,
                    'email': s.user.email,
                    'admin_accord': UserProfile.objects.filter(user=s.user).first().admin_accord
                        if UserProfile.objects.filter(user=s.user).exists() else False
                } for s in staff
            ]
            logger.info("Fetched %d medical staff for center %s", len(staff_data), tenant.label)
            return Response(staff_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching medical staff: %s", str(e))
            return Response({"error": f"Failed to fetch medical staff: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class ParamedicalStaffListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request):
        logger.debug("Received GET request to ParamedicalStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list paramedical staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = ParamedicalStaff.objects.filter(center=tenant)
            staff_data = [
                {
                    'user_id': s.user.id,
                    'class_id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'qualification': s.qualification,
                    'email': s.user.email,
                    'admin_accord': UserProfile.objects.filter(user=s.user).first().admin_accord
                        if UserProfile.objects.filter(user=s.user).exists() else False
                } for s in staff
            ]
            logger.info("Fetched %d paramedical staff for center %s", len(staff_data), tenant.label)
            return Response(staff_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching paramedical staff: %s", str(e))
            return Response({"error": f"Failed to fetch paramedical staff: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class TechnicalStaffListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request):
        logger.debug("Received GET request to TechnicalStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list technical staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = TechnicalStaff.objects.filter(center=tenant)
            staff_data = [
                {
                    'user_id': s.user.id,
                    'class_id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'qualification': s.qualification,
                    'email': s.user.email,
                    'admin_accord': UserProfile.objects.filter(user=s.user).first().admin_accord
                        if UserProfile.objects.filter(user=s.user).exists() else False
                } for s in staff
            ]
            logger.info("Fetched %d technical staff for center %s", len(staff_data), tenant.label)
            return Response(staff_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching technical staff: %s", str(e))
            return Response({"error": f"Failed to fetch technical staff: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name='dispatch')
class WorkerStaffListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request):
        logger.debug("Received GET request to WorkerStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list worker staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = WorkerStaff.objects.filter(center=tenant)
            staff_data = [
                {
                    'user_id': s.user.id,
                    'class_id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'job_title': s.job_title,
                    'email': s.user.email,
                    'admin_accord': UserProfile.objects.filter(user=s.user).first().admin_accord
                        if UserProfile.objects.filter(user=s.user).exists() else False
                } for s in staff
            ]
            logger.info("Fetched %d worker staff for center %s", len(staff_data), tenant.label)
            return Response(staff_data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching worker staff: %s", str(e))
            return Response({"error": f"Failed to fetch worker staff: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@method_decorator(csrf_exempt, name='dispatch')
class UpdateMedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def put(self, request, pk):
        try:
            medical_staff = MedicalStaff.objects.get(pk=pk)
            user = medical_staff.user
        except MedicalStaff.DoesNotExist:
            logger.error(f"MedicalStaff with ID {pk} not found.")
            return Response({'error': 'Medical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        # Validate and update user fields
        username = data.get('username', user.username)
        email = data.get('email', user.email)
        password = data.get('password', None)

        if not username or not re.match(r'^[a-zA-Z0-9]+$', username):
            return Response({'error': 'Username is required and must be alphanumeric.'}, status=status.HTTP_400_BAD_REQUEST)
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return Response({'error': 'Valid email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if password and len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        user.username = username
        user.email = email
        if password:
            user.set_password(password)
        user.save()

        # Validate and update staff fields
        nom = data.get('nom', medical_staff.nom)
        prenom = data.get('prenom', medical_staff.prenom)
        cin = data.get('cin', medical_staff.cin)
        cnom = data.get('cnom', medical_staff.cnom)
        role = data.get('role', medical_staff.role)

        if not nom or not prenom or not cin or not cnom or not role:
            return Response({'error': 'All staff fields are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{8}$', cin):
            return Response({'error': 'CIN must be exactly 8 digits.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            medical_staff.nom = nom
            medical_staff.prenom = prenom
            medical_staff.cin = cin
            medical_staff.cnom = cnom
            medical_staff.role = role
            medical_staff.save()
            logger.info(f"Medical staff {nom} {prenom} (ID: {pk}) updated by {request.user.username}.")
            user_profile = UserProfile.objects.filter(user=user).first()
            return Response({
                'success': True,
                'data': {
                    'id': medical_staff.id,
                    'nom': nom,
                    'prenom': prenom,
                    'cin': cin,
                    'cnom': cnom,
                    'role': role,
                    'username': username,
                    'email': email,
                    'admin_accord': user_profile.admin_accord if user_profile else False
                }
            }, status=status.HTTP_200_OK)
        except IntegrityError:
            return Response({'error': 'CIN must be unique.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to update MedicalStaff with ID {pk}: {str(e)}")
            return Response({'error': 'An error occurred.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class DeleteMedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def delete(self, request, pk):
        try:
            medical_staff = MedicalStaff.objects.get(pk=pk)
        except MedicalStaff.DoesNotExist:
            logger.error(f"MedicalStaff with ID {pk} not found.")
            return Response({'error': 'Medical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = medical_staff.user
        medical_staff.delete()
        user.delete()
        logger.info(f"Medical staff {medical_staff.nom} {medical_staff.prenom} (ID: {pk}) deleted by {request.user.username}.")
        return Response({'success': True, 'message': 'Medical staff deleted successfully.'}, status=status.HTTP_200_OK)
    
class UpdateParamedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def put(self, request, pk):
        try:
            paramedical_staff = ParamedicalStaff.objects.get(pk=pk)
            user = paramedical_staff.user
        except ParamedicalStaff.DoesNotExist:
            logger.error(f"ParamedicalStaff with ID {pk} not found.")
            return Response({'error': 'Paramedical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        username = data.get('username', user.username)
        email = data.get('email', user.email)
        password = data.get('password', None)

        if not username or not re.match(r'^[a-zA-Z0-9]+$', username):
            return Response({'error': 'Username is required and must be alphanumeric.'}, status=status.HTTP_400_BAD_REQUEST)
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return Response({'error': 'Valid email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if password and len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        user.username = username
        user.email = email
        if password:
            user.set_password(password)
        user.save()

        nom = data.get('nom', paramedical_staff.nom)
        prenom = data.get('prenom', paramedical_staff.prenom)
        cin = data.get('cin', paramedical_staff.cin)
        qualification = data.get('qualification', paramedical_staff.qualification)
        role = data.get('role', paramedical_staff.role)

        if not nom or not prenom or not cin or not qualification or not role:
            return Response({'error': 'All staff fields are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{8}$', cin):
            return Response({'error': 'CIN must be exactly 8 digits.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            paramedical_staff.nom = nom
            paramedical_staff.prenom = prenom
            paramedical_staff.cin = cin
            paramedical_staff.qualification = qualification
            paramedical_staff.role = role
            paramedical_staff.save()
            logger.info(f"Paramedical staff {nom} {prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': {
                'id': paramedical_staff.id,
                'nom': nom,
                'prenom': prenom,
                'cin': cin,
                'qualification': qualification,
                'role': role,
                'username': username,
                'email': email,
            }}, status=status.HTTP_200_OK)
        except IntegrityError:
            return Response({'error': 'CIN must be unique.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to update ParamedicalStaff with ID {pk}: {str(e)}")
            return Response({'error': 'An error occurred.'}, status=status.HTTP_400_BAD_REQUEST)

class DeleteParamedicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def delete(self, request, pk):
        try:
            paramedical_staff = ParamedicalStaff.objects.get(pk=pk)
        except ParamedicalStaff.DoesNotExist:
            logger.error(f"ParamedicalStaff with ID {pk} not found.")
            return Response({'error': 'Paramedical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = paramedical_staff.user
        paramedical_staff.delete()
        user.delete()
        logger.info(f"Paramedical staff {paramedical_staff.nom} {paramedical_staff.prenom} (ID: {pk}) deleted by {request.user.username}.")
        return Response({'success': True, 'message': 'Paramedical staff deleted successfully.'}, status=status.HTTP_200_OK)
class UpdateAdministrativeStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def put(self, request, pk):
        try:
            admin_staff = AdministrativeStaff.objects.get(pk=pk)
            user = admin_staff.user
        except AdministrativeStaff.DoesNotExist:
            logger.error(f"AdministrativeStaff with ID {pk} not found.")
            return Response({'error': 'Administrative staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        username = data.get('username', user.username)
        email = data.get('email', user.email)
        password = data.get('password', None)

        if not username or not re.match(r'^[a-zA-Z0-9]+$', username):
            return Response({'error': 'Username is required and must be alphanumeric.'}, status=status.HTTP_400_BAD_REQUEST)
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return Response({'error': 'Valid email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if password and len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        user.username = username
        user.email = email
        if password:
            user.set_password(password)
        user.save()

        nom = data.get('nom', admin_staff.nom)
        prenom = data.get('prenom', admin_staff.prenom)
        cin = data.get('cin', admin_staff.cin)
        job_title = data.get('job_title', admin_staff.job_title)
        role = data.get('role', admin_staff.role)

        if not nom or not prenom or not cin or not job_title or not role:
            return Response({'error': 'All staff fields are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{8}$', cin):
            return Response({'error': 'CIN must be exactly 8 digits.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            admin_staff.nom = nom
            admin_staff.prenom = prenom
            admin_staff.cin = cin
            admin_staff.job_title = job_title
            admin_staff.role = role
            admin_staff.save()
            logger.info(f"Administrative staff {nom} {prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': {
                'id': admin_staff.id,
                'nom': nom,
                'prenom': prenom,
                'cin': cin,
                'job_title': job_title,
                'role': role,
                'username': username,
                'email': email,
            }}, status=status.HTTP_200_OK)
        except IntegrityError:
            return Response({'error': 'CIN must be unique.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to update AdministrativeStaff with ID {pk}: {str(e)}")
            return Response({'error': 'An error occurred.'}, status=status.HTTP_400_BAD_REQUEST)

class DeleteAdministrativeStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def delete(self, request, pk):
        try:
            admin_staff = AdministrativeStaff.objects.get(pk=pk)
        except AdministrativeStaff.DoesNotExist:
            logger.error(f"AdministrativeStaff with ID {pk} not found.")
            return Response({'error': 'Administrative staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = admin_staff.user
        admin_staff.delete()
        user.delete()
        logger.info(f"Administrative staff {admin_staff.nom} {admin_staff.prenom} (ID: {pk}) deleted by {request.user.username}.")
        return Response({'success': True, 'message': 'Administrative staff deleted successfully.'}, status=status.HTTP_200_OK)
    

class UpdateWorkerStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN' ]
    def put(self, request, pk):
        try:
            worker_staff = WorkerStaff.objects.get(pk=pk)
            user = worker_staff.user
        except WorkerStaff.DoesNotExist:
            logger.error(f"WorkerStaff with ID {pk} not found.")
            return Response({'error': 'Worker staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        username = data.get('username', user.username)
        email = data.get('email', user.email)
        password = data.get('password', None)

        if not username or not re.match(r'^[a-zA-Z0-9]+$', username):
            return Response({'error': 'Username is required and must be alphanumeric.'}, status=status.HTTP_400_BAD_REQUEST)
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return Response({'error': 'Valid email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if password and len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        user.username = username
        user.email = email
        if password:
            user.set_password(password)
        user.save()

        nom = data.get('nom', worker_staff.nom)
        prenom = data.get('prenom', worker_staff.prenom)
        cin = data.get('cin', worker_staff.cin)
        job_title = data.get('job_title', worker_staff.job_title)
        role = data.get('role', worker_staff.role)

        if not nom or not prenom or not cin or not job_title or not role:
            return Response({'error': 'All staff fields are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{8}$', cin):
            return Response({'error': 'CIN must be exactly 8 digits.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            worker_staff.nom = nom
            worker_staff.prenom = prenom
            worker_staff.cin = cin
            worker_staff.job_title = job_title
            worker_staff.role = role
            worker_staff.save()
            logger.info(f"Worker staff {nom} {prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': {
                'id': worker_staff.id,
                'nom': nom,
                'prenom': prenom,
                'cin': cin,
                'job_title': job_title,
                'role': role,
                'username': username,
                'email': email,
            }}, status=status.HTTP_200_OK)
        except IntegrityError:
            return Response({'error': 'CIN must be unique.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to update WorkerStaff with ID {pk}: {str(e)}")
            return Response({'error': 'An error occurred.'}, status=status.HTTP_400_BAD_REQUEST)

class DeleteWorkerStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def delete(self, request, pk):
        try:
            worker_staff = WorkerStaff.objects.get(pk=pk)
        except WorkerStaff.DoesNotExist:
            logger.error(f"WorkerStaff with ID {pk} not found.")
            return Response({'error': 'Worker staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = worker_staff.user
        worker_staff.delete()
        user.delete()
        logger.info(f"Worker staff {worker_staff.nom} {worker_staff.prenom} (ID: {pk}) deleted by {request.user.username}.")
        return Response({'success': True, 'message': 'Worker staff deleted successfully.'}, status=status.HTTP_200_OK)
    
class UpdateTechnicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def put(self, request, pk):
        try:
            technical_staff = TechnicalStaff.objects.get(pk=pk)
            user = technical_staff.user
        except TechnicalStaff.DoesNotExist:
            logger.error(f"TechnicalStaff with ID {pk} not found.")
            return Response({'error': 'Technical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        username = data.get('username', user.username)
        email = data.get('email', user.email)
        password = data.get('password', None)

        if not username or not re.match(r'^[a-zA-Z0-9]+$', username):
            return Response({'error': 'Username is required and must be alphanumeric.'}, status=status.HTTP_400_BAD_REQUEST)
        if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return Response({'error': 'Valid email is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if password and len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        user.username = username
        user.email = email
        if password:
            user.set_password(password)
        user.save()

        nom = data.get('nom', technical_staff.nom)
        prenom = data.get('prenom', technical_staff.prenom)
        cin = data.get('cin', technical_staff.cin)
        job_title = data.get('job_title', technical_staff.job_title)
        role = data.get('role', technical_staff.role)

        if not nom or not prenom or not cin or not job_title or not role:
            return Response({'error': 'All staff fields are required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{8}$', cin):
            return Response({'error': 'CIN must be exactly 8 digits.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            technical_staff.nom = nom
            technical_staff.prenom = prenom
            technical_staff.cin = cin
            technical_staff.job_title = job_title
            technical_staff.role = role
            technical_staff.save()
            logger.info(f"Technical staff {nom} {prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': {
                'id': technical_staff.id,
                'nom': nom,
                'prenom': prenom,
                'cin': cin,
                'job_title': job_title,
                'role': role,
                'username': username,
                'email': email,
            }}, status=status.HTTP_200_OK)
        except IntegrityError:
            return Response({'error': 'CIN must be unique.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Failed to update TechnicalStaff with ID {pk}: {str(e)}")
            return Response({'error': 'An error occurred.'}, status=status.HTTP_400_BAD_REQUEST)

class DeleteTechnicalStaffAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']
    def delete(self, request, pk):
        try:
            technical_staff = TechnicalStaff.objects.get(pk=pk)
        except TechnicalStaff.DoesNotExist:
            logger.error(f"TechnicalStaff with ID {pk} not found.")
            return Response({'error': 'Technical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        user = technical_staff.user
        technical_staff.delete()
        user.delete()
        logger.info(f"Technical staff {technical_staff.nom} {technical_staff.prenom} (ID: {pk}) deleted by {request.user.username}.")
        return Response({'success': True, 'message': 'Technical staff deleted successfully.'}, status=status.HTTP_200_OK)

class MachineListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN','TECHNICAL']

    def get(self, request):
        logger.debug("MACHINE: Received GET request to MachineListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MACHINE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            machines = Machine.objects.filter(center=tenant)
            data = [
                {
                    "id": machine.id,
                    "brand": machine.brand,
                    "functional": machine.functional,
                    "reserve": machine.reserve,
                    "refurbished": machine.refurbished,
                    "nbre_hrs": machine.nbre_hrs,
                    "membrane": {
                        "id": machine.membrane.id,
                        "type": machine.membrane.type
                    } if machine.membrane else None,
                    "filtre": {
                        "id": machine.filtre.id,
                        "type": machine.filtre.type,
                        "sterilisation": machine.filtre.sterilisation
                    } if machine.filtre else None,
                    "center": machine.center_id
                } for machine in machines
            ]
            logger.info("MACHINE: Machine list retrieved by %s in center %s", request.user.username, tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Machine.DoesNotExist:
            logger.error("MACHINE: Machines not found for center %s", tenant.label)
            return Response({"error": "Machines not found for this center."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("MACHINE: Unexpected error fetching machines: %s", str(e))
            return Response({"error": f"Failed to fetch machines: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

# Membrane List API
class MembraneListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'TECHNICAL']

    def get(self, request):
        logger.debug("MEMBRANE: Received GET request to MembraneListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MEMBRANE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            membranes = Membrane.objects.all()  # Adjust if membranes should be tenant-specific
            data = [
                {
                    "id": membrane.id,
                    "type": membrane.type
                } for membrane in membranes
            ]
            logger.info("MEMBRANE: Membrane list retrieved by %s in center %s", request.user.username, tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except ObjectDoesNotExist as e:
            logger.error("MEMBRANE: Error fetching membranes: %s", str(e))
            return Response({"error": "Membranes not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("MEMBRANE: Unexpected error fetching membranes: %s", str(e))
            return Response({"error": f"Failed to fetch membranes: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

# Filtre List API
class FiltreListAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'TECHNICAL']

    def get(self, request):
        logger.debug("FILTRE: Received GET request to FiltreListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("FILTRE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            filtres = Filtre.objects.all()  # Adjust if filtres should be tenant-specific
            data = [
                {
                    "id": filtre.id,
                    "type": filtre.type,
                    "sterilisation": filtre.sterilisation
                } for filtre in filtres
            ]
            logger.info("FILTRE: Filtre list retrieved by %s in center %s", request.user.username, tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except ObjectDoesNotExist as e:
            logger.error("FILTRE: Error fetching filtres: %s", str(e))
            return Response({"error": "Filtres not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error("FILTRE: Unexpected error fetching filtres: %s", str(e))
            return Response({"error": f"Failed to fetch filtres: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
class AddFiltreAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'TECHNICAL']

    def post(self, request):
        logger.debug("FILTRE: Received POST request to AddFiltreAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("FILTRE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        if not is_local_admin(request.user):
            logger.warning("FILTRE: Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can add filtres."}, status=status.HTTP_403_FORBIDDEN)

        type = request.data.get('type')
        sterilisation = request.data.get('sterilisation', None)

        if not type:
            logger.error("FILTRE: Missing required field 'type'")
            return Response({"error": "Type is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            filtre = Filtre.objects.create(
                type=type,
                sterilisation=sterilisation
            )
            logger.info("FILTRE: New filtre created by %s in center %s: %s", request.user.username, tenant.label, type)
            return Response({
                "id": filtre.id,
                "type": filtre.type,
                "sterilisation": filtre.sterilisation
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error("FILTRE: Error creating filtre: %s", str(e))
            return Response({"error": f"Failed to create filtre: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

# Add Membrane API
class AddMembraneAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'TECHNICAL']

    def post(self, request):
        logger.debug("MEMBRANE: Received POST request to AddMembraneAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MEMBRANE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        if not is_local_admin(request.user):
            logger.warning("MEMBRANE: Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can add membranes."}, status=status.HTTP_403_FORBIDDEN)

        type = request.data.get('type')
        if not type:
            logger.error("MEMBRANE: Missing required field 'type'")
            return Response({"error": "Type is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            membrane = Membrane.objects.create(type=type)
            logger.info("MEMBRANE: New membrane created by %s in center %s: %s", request.user.username, tenant.label, type)
            return Response({
                "id": membrane.id,
                "type": membrane.type
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error("MEMBRANE: Error creating membrane: %s", str(e))
            return Response({"error": f"Failed to create membrane: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        
class VerifyUserAPIView(APIView):
    def post(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            logger.warning("No user_id provided in verification request")
            return Response(
                {"error": "user_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        form = VerificationForm(request.data)
        if not form.is_valid():
            logger.warning("Invalid form data: %s", form.errors)
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

        verification_code = form.cleaned_data['verification_code']
        
        try:
            user = User.objects.get(id=user_id)
            user_profile = user.verification_profile
        except User.DoesNotExist:
            logger.error("No user found for user_id %s", user_id)
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except UserProfile.DoesNotExist:
            logger.error("No UserProfile found for user_id %s", user_id)
            return Response(
                {"error": "User profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if user_profile.verify_code(verification_code):
            response_data = {
                "message": "Verification successful.",
                "is_verified": user_profile.is_verified,
                "admin_accord": user_profile.admin_accord,
                "has_role_privileges": user_profile.has_role_privileges()
            }
            logger.info("User %s registered via API", user.username)
            return Response(response_data, status.HTTP_200_OK)
        else:
            logger.warning("Failed verification attempt for user %s with code %s",
                         user.username, verification_code)
            return Response(
                {"error": "Invalid verification code."},
                status=status.HTTP_400_BAD_REQUEST
            )

class GrantAdminAccordAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def post(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            logger.warning("No user_id provided in admin accord request")
            return Response(
                {"error": "user_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(id=user_id)
            user_profile = user.verification_profile
        except User.DoesNotExist:
            logger.error("User with ID %s not found", user_id)
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        except UserProfile.DoesNotExist:
            logger.error("No UserProfile found for user ID %s", user_id)
            return Response(
                {"error": "User profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if user_profile.grant_admin_accord():
            response_data = {
                "message": "Admin accord granted successfully.",
                "user_id": user.id,
                "username": user.username,
                "is_verified": user_profile.is_verified,
                "admin_accord": user_profile.admin_accord,
                "has_role_privileges": user_profile.has_role_privileges()
            }
            logger.info("Admin accord granted for user %s by admin %s", user.username, request.user.username)
            return Response(response_data, status=status.HTTP_200_OK)
        else:
            logger.warning("Failed to grant admin accord for user %s: not verified", user.username)
            return Response(
                {"error": "User must be verified before granting admin accord."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class UpdateUserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.debug("Received POST request to UpdateUserProfileAPIView: data=%s, user=%s",
                     request.data, request.user.username)

        # Validate tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for API request: user=%s", request.user.username)
            return Response(
                {"error": "Invalid center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )
        logger.debug("Tenant validated: label=%s", tenant.label)

        # Check if user is LOCAL_ADMIN
        try:
            staff = AdministrativeStaff.objects.get(user=request.user, center=tenant)
            logger.debug("Found AdministrativeStaff: user=%s, role=%s, center=%s",
                         request.user.username, staff.role, tenant.label)
            if staff.role != 'LOCAL_ADMIN':
                logger.warning("User %s attempted to update profile without LOCAL_ADMIN role: role=%s",
                               request.user.username, staff.role)
                return Response(
                    {"error": "Only LOCAL_ADMIN users can update profiles."},
                    status=status.HTTP_403_FORBIDDEN
                )
        except AdministrativeStaff.DoesNotExist:
            logger.warning("User %s is not an AdministrativeStaff in center %s",
                           request.user.username, tenant.label)
            return Response(
                {"error": "You are not authorized for this center."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Validate user_id
        user_id = request.data.get('user_id')
        if not user_id:
            logger.warning("No user_id provided in update profile request: user=%s", request.user.username)
            return Response(
                {"error": "user_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        logger.debug("Target user_id: %s", user_id)

        # Fetch target user and profile
        try:
            target_user = User.objects.get(id=user_id)
            logger.debug("Found target user: username=%s, id=%s", target_user.username, target_user.id)
            try:
                user_profile = target_user.verification_profile
                logger.debug("Found UserProfile for user_id=%s: is_verified=%s, admin_accord=%s",
                             user_id, user_profile.is_verified, user_profile.admin_accord)
            except UserProfile.DoesNotExist:
                logger.error("No UserProfile found for user_id=%s", user_id)
                return Response(
                    {"error": "User profile not found."},
                    status=status.HTTP_404_NOT_FOUND
                )
        except User.DoesNotExist:
            logger.error("No user found for user_id=%s", user_id)
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verify target user is associated with the tenant
        staff_types = [AdministrativeStaff, ParamedicalStaff, TechnicalStaff, MedicalStaff, WorkerStaff]
        is_tenant_staff = False
        for staff_type in staff_types:
            if staff_type.objects.filter(user=target_user, center=tenant).exists():
                is_tenant_staff = True
                logger.debug("Target user %s is %s in center %s",
                             target_user.username, staff_type.__name__, tenant.label)
                break
        if not is_tenant_staff:
            logger.warning("User %s is not associated with center %s",
                           target_user.username, tenant.label)
            return Response(
                {"error": "User is not associated with this center."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate admin_accord
        admin_accord = request.data.get('admin_accord', True)
        logger.debug("Received admin_accord: %s (type=%s)", admin_accord, type(admin_accord))
        if not isinstance(admin_accord, bool):
            logger.warning("Invalid admin_accord value for user_id=%s: value=%s", user_id, admin_accord)
            return Response(
                {"error": "admin_accord must be a boolean."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update profile
        logger.debug("Before update: user_id=%s, admin_accord=%s", user_id, user_profile.admin_accord)
        user_profile.admin_accord = admin_accord
        user_profile.save()
        user_profile.refresh_from_db()  # Ensure we get the latest state
        logger.debug("After update: user_id=%s, admin_accord=%s, has_role_privileges=%s",
                     user_id, user_profile.admin_accord, user_profile.has_role_privileges())

        logger.info("User %s updated profile for user %s in center %s: admin_accord=%s",
                    request.user.username, target_user.username, tenant.label, admin_accord)

        return Response({
            "message": "Profile updated successfully.",
            "is_verified": user_profile.is_verified,
            "admin_accord": user_profile.admin_accord,
            "has_role_privileges": user_profile.has_role_privileges()
        }, status=status.HTTP_200_OK)
    

class ExportPDFAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'SUBMITTER']

    def get(self, request):
        center = request.tenant
        if not center:
            logger.error("No tenant provided for ExportPDFAPIView")
            return Response({"error": "No center found for this subdomain."}, status=404)

        patients = Patient.objects.filter(center=center)
        sessions = HemodialysisSession.objects.filter(medical_activity__patient__center=center)
        diseases = TransmittableDisease.objects.filter(medical_activity__patient__center=center)
        complications = Complications.objects.filter(medical_activity__patient__center=center)
        transplantations = Transplantation.objects.filter(medical_activity__patient__center=center)
        deceased_patients = patients.filter(status='DECEASED')
        medical_staff = MedicalStaff.objects.filter(center=center)
        paramedical_staff = ParamedicalStaff.objects.filter(center=center)
        administrative_staff = AdministrativeStaff.objects.filter(center=center)
        technical_staff = TechnicalStaff.objects.filter(center=center)
        worker_staff = WorkerStaff.objects.filter(center=center)
        machines = Machine.objects.filter(center=center)

        context = {
            'center': center,
            'patients': patients,
            'sessions': sessions,
            'diseases': diseases,
            'complications': complications,
            'transplantations': transplantations,
            'deceased_patients': deceased_patients,
            'total_deaths': deceased_patients.count(),
            'medical_staff': medical_staff,
            'paramedical_staff': paramedical_staff,
            'administrative_staff': administrative_staff,
            'technical_staff': technical_staff,
            'worker_staff': worker_staff,
            'machines': machines,
            'total_diseases': diseases.count(),
            'total_complications': complications.count(),
            'report_date': datetime.now().strftime('%Y-%m-%d'),
        }

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
        elements = []

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name='Title',
            fontSize=16,
            fontName='Helvetica-Bold',
            alignment=1,
            spaceAfter=12,
        )
        subtitle_style = ParagraphStyle(
            name='Subtitle',
            fontSize=12,
            fontName='Helvetica-Bold',
            textColor=colors.black,
            leading=14,
            spaceBefore=10,
            spaceAfter=8,
        )
        normal_style = styles['Normal']
        normal_style.fontSize = 10

        # Center Information
        elements.append(Paragraph("Center Information", title_style))
        center_data = [
            ['Name', center.label],
            ['Address', center.adresse or 'N/A'],
            ['Delegation', center.delegation.name if center.delegation else 'N/A'],
            ['Telephone', center.tel or 'N/A'],
            ['Email', center.mail or 'N/A'],
        ]
        center_table = Table(center_data, colWidths=[5*cm, 12*cm])
        center_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
            ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
            ('ALIGN', (1,0), (1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('BACKGROUND', (0,0), (-1,-1), colors.white),
            ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('BACKGROUND', (0,2), (-1,2), colors.lightgrey),
            ('BACKGROUND', (0,4), (-1,4), colors.lightgrey),
        ]))
        elements.append(center_table)
        elements.append(Spacer(1, 0.5*cm))

        # Staff Members
        elements.append(Paragraph("Staff Members", title_style))

        # Administrative and Technical Staff
        elements.append(Paragraph("Administrative Staff", subtitle_style))
        admin_data = [['Name', 'CIN', 'Details']]
        for staff in administrative_staff:
            admin_data.append([
                f"{staff.nom} {staff.prenom}",
                staff.cin,
                f"Job Title: {staff.job_title}",
            ])
        for staff in technical_staff:
            admin_data.append([
                f"{staff.nom} {staff.prenom}",
                staff.cin,
                f"Qualification: {staff.qualification}",
            ])
        if len(admin_data) > 1:
            admin_table = Table(admin_data, colWidths=[6*cm, 4*cm, 7*cm])
            admin_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(admin_table)
        else:
            elements.append(Paragraph("No Administrative Staff recorded.", normal_style))
        elements.append(Spacer(1, 0.3*cm))

        # Para & Medical Staff
        elements.append(Paragraph("Para & Medical Staff", subtitle_style))
        para_medical_data = [['Name', 'CIN', 'Details']]
        for staff in medical_staff:
            para_medical_data.append([
                f"{staff.nom} {staff.prenom}",
                staff.cin,
                f"CNOM: {staff.cnom}",
            ])
        for staff in paramedical_staff:
            para_medical_data.append([
                f"{staff.nom} {staff.prenom}",
                staff.cin,
                f"Qualification: {staff.qualification}",
            ])
        if len(para_medical_data) > 1:
            para_medical_table = Table(para_medical_data, colWidths=[6*cm, 4*cm, 7*cm])
            para_medical_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(para_medical_table)
        else:
            elements.append(Paragraph("No Para & Medical Staff recorded.", normal_style))
        elements.append(Spacer(1, 0.3*cm))

        # Workers Staff
        elements.append(Paragraph("Workers Staff", subtitle_style))
        worker_data = [['Name', 'CIN', 'Details']]
        for staff in worker_staff:
            worker_data.append([
                f"{staff.nom} {staff.prenom}",
                staff.cin,
                f"Job Title: {staff.job_title}",
            ])
        if len(worker_data) > 1:
            worker_table = Table(worker_data, colWidths=[6*cm, 4*cm, 7*cm])
            worker_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(worker_table)
        else:
            elements.append(Paragraph("No Workers Staff recorded.", normal_style))
        elements.append(Spacer(1, 0.5*cm))

        # Equipment
        elements.append(Paragraph("Equipment", title_style))
        machine_data = [['Brand', 'Functional', 'Reserve', 'Refurbished', 'Hours', 'Membrane', 'Filtre']]
        for machine in machines:
            machine_data.append([
                machine.brand,
                'Yes' if machine.functional else 'No',
                'Yes' if machine.reserve else 'No',
                'Yes' if machine.refurbished else 'No',
                str(machine.nbre_hrs),
                machine.membrane.type,
                f"{machine.filtre.type} ({machine.filtre.sterilisation})" if machine.filtre.sterilisation else machine.filtre.type,
            ])
        if len(machine_data) > 1:
            machine_table = Table(machine_data, colWidths=[3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2*cm, 2.5*cm, 3*cm])
            machine_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(machine_table)
        else:
            elements.append(Paragraph("No machines recorded.", normal_style))
        elements.append(Spacer(1, 0.5*cm))

        # Activity
        elements.append(Paragraph("Activity", title_style))

        # Hemodialysis Sessions
        elements.append(Paragraph("Hemodialysis Sessions", subtitle_style))
        session_data = [['Type', 'Method', 'Date', 'Doctor', 'Pre-BP', 'Post-BP', 'Duration', 'Access', 'Severity']]
        for session in sessions:
            session_data.append([
                session.type.name,
                session.method.name,
                session.date_of_session.strftime('%Y-%m-%d'),
                f"{session.responsible_doc.nom} {session.responsible_doc.prenom}",
                f"{session.pre_dialysis_bp:.1f}" if session.pre_dialysis_bp is not None else 'N/A',
                f"{session.post_dialysis_bp:.1f}" if session.post_dialysis_bp is not None else 'N/A',
                f"{session.dialysis_duration:.1f}" if session.dialysis_duration is not None else 'N/A',
                session.vascular_access_type or 'N/A',
                session.severity_of_case or 'N/A',
            ])
        if len(session_data) > 1:
            session_table = Table(session_data, colWidths=[2.5*cm, 2.5*cm, 2.5*cm, 3.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 2*cm, 2*cm])
            session_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(session_table)
        else:
            elements.append(Paragraph("No hemodialysis sessions recorded.", normal_style))
        elements.append(Spacer(1, 0.3*cm))

        # Transplantations
        elements.append(Paragraph("Transplantations", subtitle_style))
        transplantation_data = [['Type', 'Date of Operation', 'Notes']]
        for transplantation in transplantations:
            transplantation_data.append([
                transplantation.transplantation.label_transplantation,
                transplantation.date_operation.strftime('%Y-%m-%d'),
                transplantation.notes or 'No notes',
            ])
        if len(transplantation_data) > 1:
            transplantation_table = Table(transplantation_data, colWidths=[6*cm, 5*cm, 6*cm])
            transplantation_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(transplantation_table)
        else:
            elements.append(Paragraph("No transplantations recorded.", normal_style))
        elements.append(Spacer(1, 0.5*cm))

        # Morbidity
        elements.append(Paragraph("Morbidity", title_style))

        # Transmittable Diseases
        elements.append(Paragraph("Transmittable Diseases", subtitle_style))
        disease_data = [['Disease', 'Transmission Type', 'Date of Contraction']]
        for disease in diseases:
            disease_data.append([
                disease.disease.label_disease,
                disease.disease.type_of_transmission,
                disease.date_of_contraction.strftime('%Y-%m-%d'),
            ])
        if len(disease_data) > 1:
            disease_table = Table(disease_data, colWidths=[6*cm, 6*cm, 5*cm])
            disease_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(disease_table)
            elements.append(Paragraph(f"Total Incidents: {context['total_diseases']}", normal_style))
        else:
            elements.append(Paragraph("No transmittable diseases recorded.", normal_style))
        elements.append(Spacer(1, 0.3*cm))

        # Complications
        elements.append(Paragraph("Complications", subtitle_style))
        complication_data = [['Complication', 'Notes', 'Date of Contraction']]
        for complication in complications:
            complication_data.append([
                complication.complication.label_complication,
                complication.notes or 'No notes',
                complication.date_of_contraction.strftime('%Y-%m-%d'),
            ])
        if len(complication_data) > 1:
            complication_table = Table(complication_data, colWidths=[6*cm, 6*cm, 5*cm])
            complication_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(complication_table)
            elements.append(Paragraph(f"Total Incidents: {context['total_complications']}", normal_style))
        else:
            elements.append(Paragraph("No complications recorded.", normal_style))
        elements.append(Spacer(1, 0.5*cm))

        # Mortality
        elements.append(Paragraph("Mortality", title_style))

        # Deceased Patients
        elements.append(Paragraph("Deceased Patients", subtitle_style))
        deceased_data = [['Name', 'CIN', 'Decease Note']]
        for patient in deceased_patients:
            deceased_data.append([
                f"{patient.nom} {patient.prenom}",
                patient.cin,
                patient.decease_note or 'No note provided',
            ])
        if len(deceased_data) > 1:
            deceased_table = Table(deceased_data, colWidths=[6*cm, 4*cm, 7*cm])
            deceased_table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
                ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ]))
            elements.append(deceased_table)
        else:
            elements.append(Paragraph("No deaths recorded.", normal_style))
        elements.append(Spacer(1, 0.3*cm))

        # Mortality Totals
        elements.append(Paragraph("Mortality Totals", subtitle_style))
        elements.append(Paragraph(f"Total Deaths: {context['total_deaths']}", normal_style))
        elements.append(Spacer(1, 0.5*cm))

        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="center_report_{center.label}_{context["report_date"]}.pdf"'
        response.write(pdf)
        return response
    
class CenterDetailView(APIView):
    permission_classes = [IsAuthenticated, RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'MEDICAL_PARA_STAFF','WORKER', 'TECHNICAl', 'VIEWER']  # All roles

    def get(self, request):
        try:
            tenant = getattr(request, 'tenant', None)
            if not tenant:
                logger.error("No tenant found for request by user %s", request.user.username)
                return Response({"error": "No center associated with this request"}, status=400)

            center = Center.objects.get(id=tenant.id)
            center_data = {
                "id": center.id,
                "sub_domain": center.sub_domain,
                "label": center.label,
                "tel": center.tel,
                "mail": center.mail,
                "adresse": center.adresse,
                "governorate": {
                    "id": center.governorate.id,
                    "name": center.governorate.name,
                    "code": center.governorate.code
                } if center.governorate else None,
                "delegation": {
                    "id": center.delegation.id,
                    "name": center.delegation.name,
                    "code": center.delegation.code,
                    "governorate_id": center.delegation.governorate.id
                } if center.delegation else None,
                "type_center": center.type_center,
                "code_type_hemo": center.code_type_hemo,
                "name_type_hemo": center.name_type_hemo,
                "center_code": center.center_code
            }
            return Response(center_data)
        except Center.DoesNotExist:
            logger.error("Center not found for tenant ID %s by user %s", tenant.id, request.user.username)
            return Response({"error": "Center not found"}, status=404)
        except Exception as e:
            logger.error("Error fetching center details for user %s: %s", request.user.username, str(e))
            return Response({"error": "Internal server error"}, status=500)
        

class MedicalStaffDetailAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request, staff_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            medical_staff = MedicalStaff.objects.get(id=staff_id, center=center)
            data = {
                'id': medical_staff.id,
                'nom': medical_staff.nom,
                'prenom': medical_staff.prenom,
                'cin': medical_staff.cin,
                'cnom': medical_staff.cnom,
                'role': medical_staff.role,
                'username': medical_staff.user.username,
                'email': medical_staff.user.email,
            }
            return Response(data)
        except Center.DoesNotExist:
            logger.error("Center not found for tenant %s", request.tenant.sub_domain)
            return Response({'error': 'Center not found for this tenant.'}, status=status.HTTP_404_NOT_FOUND)
        except MedicalStaff.DoesNotExist:
            logger.error("Medical staff not found with ID %s for center %s", staff_id, center.id)
            return Response({'error': 'Medical staff not found.'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            logger.error("Medical staff ID %s has no associated user", staff_id)
            return Response({'error': 'User profile not found for this staff.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class WorkerStaffDetailAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request, staff_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            worker_staff = WorkerStaff.objects.get(id=staff_id, center=center)
            data = {
                'id': worker_staff.id,
                'nom': worker_staff.nom,
                'prenom': worker_staff.prenom,
                'cin': worker_staff.cin,
                'job_title': worker_staff.job_title,
                'role': worker_staff.role,
                'username': worker_staff.user.username,
                'email': worker_staff.user.email,
            }
            return Response(data)
        except Center.DoesNotExist:
            logger.error("Center not found for tenant %s", request.tenant.sub_domain)
            return Response({'error': 'Center not found for this tenant.'}, status=status.HTTP_404_NOT_FOUND)
        except WorkerStaff.DoesNotExist:
            logger.error("Worker staff not found with ID %s for center %s", staff_id, center.id)
            return Response({'error': 'Worker staff not found.'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            logger.error("Worker staff ID %s has no associated user", staff_id)
            return Response({'error': 'User profile not found for this staff.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ParamedicalStaffDetailAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request, staff_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            paramedical_staff = ParamedicalStaff.objects.get(id=staff_id, center=center)
            data = {
                'id': paramedical_staff.id,
                'nom': paramedical_staff.nom,
                'prenom': paramedical_staff.prenom,
                'cin': paramedical_staff.cin,
                'qualification': paramedical_staff.qualification,
                'role': paramedical_staff.role,
                'username': paramedical_staff.user.username,
                'email': paramedical_staff.user.email,
            }
            return Response(data)
        except Center.DoesNotExist:
            logger.error("Center not found for tenant %s", request.tenant.sub_domain)
            return Response({'error': 'Center not found for this tenant.'}, status=status.HTTP_404_NOT_FOUND)
        except ParamedicalStaff.DoesNotExist:
            logger.error("Paramedical staff not found with ID %s for center %s", staff_id, center.id)
            return Response({'error': 'Paramedical staff not found.'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            logger.error("Paramedical staff ID %s has no associated user", staff_id)
            return Response({'error': 'User profile not found for this staff.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdministrativeStaffDetailAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request, staff_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            administrative_staff = AdministrativeStaff.objects.get(id=staff_id, center=center)
            data = {
                'id': administrative_staff.id,
                'nom': administrative_staff.nom,
                'prenom': administrative_staff.prenom,
                'cin': administrative_staff.cin,
                'job_title': administrative_staff.job_title,
                'role': administrative_staff.role,
                'username': administrative_staff.user.username,
                'email': administrative_staff.user.email,
            }
            return Response(data)
        except Center.DoesNotExist:
            logger.error("Center not found for tenant %s", request.tenant.sub_domain)
            return Response({'error': 'Center not found for this tenant.'}, status=status.HTTP_404_NOT_FOUND)
        except AdministrativeStaff.DoesNotExist:
            logger.error("Administrative staff not found with ID %s for center %s", staff_id, center.id)
            return Response({'error': 'Administrative staff not found.'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            logger.error("Administrative staff ID %s has no associated user", staff_id)
            return Response({'error': 'User profile not found for this staff.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TechnicalStaffDetailAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN']

    def get(self, request, staff_id):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            technical_staff = TechnicalStaff.objects.get(id=staff_id, center=center)
            data = {
                'id': technical_staff.id,
                'nom': technical_staff.nom,
                'prenom': technical_staff.prenom,
                'cin': technical_staff.cin,
                'job_title': technical_staff.job_title,
                'role': technical_staff.role,
                'username': technical_staff.user.username,
                'email': technical_staff.user.email,
            }
            return Response(data)
        except Center.DoesNotExist:
            logger.error("Center not found for tenant %s", request.tenant.sub_domain)
            return Response({'error': 'Center not found for this tenant.'}, status=status.HTTP_404_NOT_FOUND)
        except TechnicalStaff.DoesNotExist:
            logger.error("Technical staff not found with ID %s for center %s", staff_id, center.id)
            return Response({'error': 'Technical staff not found.'}, status=status.HTTP_404_NOT_FOUND)
        except AttributeError:
            logger.error("Technical staff ID %s has no associated user", staff_id)
            return Response({'error': 'User profile not found for this staff.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class UserDetailsAPIView(APIView):
    permission_classes = [RoleBasedPermission]
    allowed_roles = ['LOCAL_ADMIN', 'SUBMITTER', 'MEDICAL_PARA_STAFF', 'TECHNICAL', 'VIEWER', 'WORKER']

    def get(self, request):
        logger.debug("Received GET request to UserDetailsAPIView. User: %s", request.user.username)
        if not request.user.is_authenticated:
            logger.error("Unauthenticated user attempted to access user details")
            return Response({"error": "User must be authenticated."}, status=status.HTTP_401_UNAUTHORIZED)

        tenant = getattr(request, 'tenant', None)
        user_data = {
            "username": request.user.username,
            "email": request.user.email,
            "is_superuser": request.user.is_superuser,
            "center": None,
            "role": None,
            "profile": {},
            "staff_details": None,
            "staff_type": None,
        }

        # Handle superuser case
        if request.user.is_superuser:
            user_data["role"] = "SUPER_ADMIN"
            logger.info("Superuser %s accessed user details", request.user.username)
            return Response(user_data, status=status.HTTP_200_OK)

        # Handle tenant-specific users
        if not tenant:
            logger.error("No tenant found for user %s", request.user.username)
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        user_data["center"] = {
            "id": tenant.id,
            "label": tenant.label,
            "sub_domain": tenant.sub_domain,
        }

        # Fetch UserProfile
        try:
            profile = UserProfile.objects.get(user=request.user)
            user_data["profile"] = {
                "is_verified": profile.is_verified,
                "has_role_privileges": profile.has_role_privileges(),
                "admin_accord": profile.admin_accord,
            }
        except UserProfile.DoesNotExist:
            logger.warning("No UserProfile found for user %s", request.user.username)
            user_data["profile"] = {"is_verified": False, "has_role_privileges": False, "admin_accord": False}

        # Check staff profiles using related names
        staff_mappings = [
            ('administrative_profile', AdministrativeStaff, 'Administrative'),
            ('medical_profile', MedicalStaff, 'Medical'),
            ('paramedical_profile', ParamedicalStaff, 'Paramedical'),
            ('technical_profile', TechnicalStaff, 'Technical'),
            ('worker_profile', WorkerStaff, 'Worker'),
        ]

        for related_name, model, staff_type in staff_mappings:
            try:
                staff = getattr(request.user, related_name)
                user_data["role"] = staff.role
                user_data["staff_type"] = staff_type
                user_data["staff_details"] = {
                    "nom": staff.nom,
                    "prenom": staff.prenom,
                    "cin": staff.cin,
                }
                # Add model-specific fields
                if staff_type == 'Administrative' or staff_type == 'Worker':
                    user_data["staff_details"]["job_title"] = staff.job_title
                elif staff_type == 'Medical':
                    user_data["staff_details"]["cnom"] = staff.cnom
                elif staff_type in ['Paramedical', 'Technical']:
                    user_data["staff_details"]["qualification"] = staff.qualification
                logger.info("Found %s profile for user %s in center %s", staff_type, request.user.username, tenant.label)
                break
            except model.DoesNotExist:
                continue

        if not user_data["role"]:
            logger.warning("No staff profile found for user %s in center %s", request.user.username, tenant.label)
            user_data["role"] = "NO_ROLE"

        logger.info("User details retrieved for %s in center %s", request.user.username, tenant.label)
        return Response(user_data, status=status.HTTP_200_OK)