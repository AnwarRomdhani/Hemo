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
from .models import UserProfile,TypeHemo,MethodHemo, Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, Delegation, Patient, CNAM, MethodHemo, MedicalActivity, TransmittableDiseaseRef, ComplicationsRef, Machine, HemodialysisSession, TransmittableDisease, Complications, Transplantation, TransplantationRef
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

logger = logging.getLogger(__name__)

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
def declare_deceased(request, pk):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for declare_deceased")
        return JsonResponse({'error': 'No center found for this subdomain.'}, status=404)

    patient = get_object_or_404(Patient, pk=pk, center=center)
    if patient.status == 'DECEASED':
        return JsonResponse({'error': 'Patient is already deceased.'}, status=400)

    user_roles = []
    for staff_type in [MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, TechnicalStaff]:
        try:
            staff = staff_type.objects.get(user=request.user, center=center)
            user_roles.append(staff.role)
        except staff_type.DoesNotExist:
            continue
    if not any(role in ['LOCAL_ADMIN', 'SUBMITTER'] for role in user_roles):
        logger.warning("Permission denied for user %s in center %s", request.user.username, center.label)
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    if request.method == 'POST':
        form = DeceasePatientForm(request.POST, instance=patient)
        if form.is_valid():
            patient.status = 'DECEASED'
            form.save()
            logger.info("Patient %s declared deceased by user %s in center %s", patient, request.user.username, center.label)
            return JsonResponse({'success': 'Patient declared deceased successfully.'})
        else:
            errors = form.errors.as_json()
            logger.error("Form validation failed for declare_deceased: %s", errors)
            return JsonResponse({'error': 'Form validation failed.', 'errors': errors}, status=400)
    else:
        return JsonResponse({'error': 'Invalid request method.'}, status=405)

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

@user_passes_test(is_local_admin)
def add_machine(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for add_machine")
        return render(request, 'centers/error.html', {'message': 'No center selected. Please access via a valid tenant.'}, status=400)
    if request.method == 'POST':
        form = MachineForm(request.POST, center=center)
        if form.is_valid():
            machine = form.save()
            logger.info("Machine saved: %s for center %s", machine, center.label)
            return redirect('center_detail')
        else:
            logger.warning("Machine form is invalid: %s", form.errors)
    else:
        form = MachineForm(center=center)
    return render(request, 'centers/add_machine.html', {'form': form, 'center': center})

@user_passes_test(is_local_admin)
def add_technical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = TechnicalStaffForm(request.POST, center=center)
        if form.is_valid():
            staff = form.save()
            logger.info("Technical staff saved: %s", staff)
            return redirect('center_detail')
        else:
            logger.warning("Technical staff form is invalid: %s", form.errors)
    else:
        form = TechnicalStaffForm(center=center)
    return render(request, 'centers/add_technical_staff.html', {
        'form': form,
        'center': center
    })

@user_passes_test(is_local_admin)
def add_medical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = MedicalStaffForm(request.POST, center=center)
        if form.is_valid():
            staff = form.save()
            logger.info("Medical staff saved: %s", staff)
            return redirect('center_detail')
        else:
            logger.warning("Medical staff form is invalid: %s", form.errors)
    else:
        form = MedicalStaffForm(center=center)
    return render(request, 'centers/add_medical_staff.html', {
        'form': form,
        'center': center
    })

@user_passes_test(is_local_admin)
def add_paramedical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = ParamedicalStaffForm(request.POST, center=center)
        logger.debug("POST data for add_paramedical_staff: %s", dict(request.POST))
        if form.is_valid():
            try:
                staff = form.save()
                logger.info("Paramedical staff saved: %s for center %s", staff, center.label)
                return redirect('center_detail')
            except Exception as e:
                logger.error("Error saving paramedical staff: %s", str(e))
                form.add_error(None, f"Error: {str(e)}")
        else:
            logger.warning("Paramedical staff form is invalid: %s", form.errors)
    else:
        form = ParamedicalStaffForm(center=center)
    return render(request, 'centers/add_paramedical_staff.html', {
        'form': form,
        'center': center,
        'error': form.errors
    })

@user_passes_test(is_local_admin)
def add_administrative_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = AdministrativeStaffForm(request.POST, center=center)
        if form.is_valid():
            staff = form.save()
            logger.info("Administrative staff saved: %s", staff)
            return redirect('center_detail')
        else:
            logger.warning("Administrative staff form is invalid: %s", form.errors)
    else:
        form = AdministrativeStaffForm(center=center)
    return render(request, 'centers/add_administrative_staff.html', {
        'form': form,
        'center': center
    })

@user_passes_test(is_local_admin)
def add_worker_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = WorkerStaffForm(request.POST, center=center)
        if form.is_valid():
            staff = form.save()
            logger.info("Worker staff saved: %s", staff)
            return redirect('center_detail')
        else:
            logger.warning("Worker staff form is invalid: %s", form.errors)
    else:
        form = WorkerStaffForm(center=center)
    return render(request, 'centers/add_worker_staff.html', {
        'form': form,
        'center': center
    })

@user_passes_test(is_medical_para_staff)
def add_patient(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = PatientForm(request.POST, center=center)
        if form.is_valid():
            form.save()
            return redirect('center_detail')
        else:
            logger.warning("Patient form is invalid: %s", form.errors)
    else:
        form = PatientForm(center=center)
    return render(request, 'centers/add_patient.html', {
        'form': form,
        'center': center
    })

def add_cnam(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)
    number = request.POST.get('number')
    if not number:
        return JsonResponse({'error': 'CNAM number is required'}, status=400)
    try:
        cnam, created = CNAM.objects.get_or_create(number=number)
        return JsonResponse({'id': cnam.id, 'number': cnam.number})
    except Exception as e:
        logger.error("Error adding CNAM: %s", str(e))
        return JsonResponse({'error': str(e)}, status=500)

def load_delegations(request):
    governorate_id = request.GET.get('governorate_id')
    logger.debug("Loading delegations for governorate_id: %s", governorate_id)
    delegations = Delegation.objects.filter(governorate_id=governorate_id).order_by('name')
    logger.debug("Delegations found: %s", list(delegations.values('id', 'name')))
    return render(request, 'centers/delegation_dropdown_list_options.html', {'delegations': delegations})

def load_methods(request):
    type_hemo_id = request.GET.get('type_hemo_id')
    logger.debug("Loading methods for type_hemo_id: %s", type_hemo_id)
    methods = MethodHemo.objects.filter(type_hemo_id=type_hemo_id).order_by('name')
    logger.debug("Methods found: %s", list(methods.values('id', 'name')))
    return render(request, 'centers/method_dropdown_list_options.html', {'methods': methods})

@login_required
def list_patients(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for list_patients")
        return render(request, 'centers/404.html', status=404)
    if not is_viewer(request.user):
        return HttpResponse("Permission denied.", status=403)
    patients = center.patient_staff.all()
    logger.debug("Patients fetched for center %s: %s", center.label, list(patients.values('nom', 'prenom')))
    return render(request, 'centers/list_patients.html', {
        'center': center,
        'patients': patients,
    })

@user_passes_test(is_local_admin)
def add_disease_ref(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for add_disease_ref")
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = TransmittableDiseaseRefForm(request.POST)
        if form.is_valid():
            form.save()
            logger.info("TransmittableDiseaseRef saved: %s", form.cleaned_data['label_disease'])
            return redirect('center_detail')
        else:
            logger.warning("TransmittableDiseaseRef form is invalid: %s", form.errors)
    else:
        form = TransmittableDiseaseRefForm()
    return render(request, 'centers/add_disease_ref.html', {
        'form': form,
        'center': center
    })

@user_passes_test(is_local_admin)
def add_complication_ref(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for add_complication_ref")
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = ComplicationsRefForm(request.POST)
        if form.is_valid():
            form.save()
            logger.info("ComplicationsRef saved: %s", form.cleaned_data['label_complication'])
            return redirect('center_detail')
        else:
            logger.warning("ComplicationsRef form is invalid: %s", form.errors)
    else:
        form = ComplicationsRefForm()
    return render(request, 'centers/add_complication_ref.html', {
        'form': form,
        'center': center
    })

@login_required
def patient_detail(request, pk):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for patient_detail")
        return render(request, 'centers/404.html', status=404)
    if not is_viewer(request.user):
        return HttpResponse("Permission denied.", status=403)
    patient = get_object_or_404(Patient, pk=pk, center=center)
    logger.debug("Patient fetched: %s for center %s", patient, center.label)
    
    if request.method == 'POST' and is_submitter(request.user):
        session_form = HemodialysisSessionForm(request.POST, center=center, prefix='session')
        disease_form = TransmittableDiseaseForm(request.POST, center=center, prefix='disease')
        complication_form = ComplicationsForm(request.POST, center=center, prefix='complication')
        transplantation_form = TransplantationForm(request.POST, center=center, prefix='transplantation')
        if 'session_submit' in request.POST and session_form.is_valid():
            session = session_form.save(commit=False)
            try:
                medical_activity = patient.medical_activity
            except MedicalActivity.DoesNotExist:
                logger.warning("No MedicalActivity for patient %s, creating one", patient)
                medical_activity = MedicalActivity.objects.create(
                    patient=patient,
                    created_at=patient.entry_date
                )
            session.medical_activity = medical_activity
            try:
                session.save()
                logger.info("Hemodialysis session saved for patient %s: %s", patient, session)
                return redirect('patient_detail', pk=pk)
            except Exception as e:
                logger.error("Error saving hemodialysis session: %s", str(e))
                session_form.add_error(None, f"Error saving session: {str(e)}")
        elif 'disease_submit' in request.POST and disease_form.is_valid():
            disease = disease_form.save(commit=False)
            try:
                medical_activity = patient.medical_activity
            except MedicalActivity.DoesNotExist:
                logger.warning("No MedicalActivity for patient %s, creating one", patient)
                medical_activity = MedicalActivity.objects.create(
                    patient=patient,
                    created_at=patient.entry_date
                )
            disease.medical_activity = medical_activity
            try:
                disease.save()
                logger.info("Transmittable disease saved for patient %s: %s", patient, disease)
                return redirect('patient_detail', pk=pk)
            except Exception as e:
                logger.error("Error saving transmittable disease: %s", str(e))
                disease_form.add_error(None, f"Error saving disease: {str(e)}")
        elif 'complication_submit' in request.POST and complication_form.is_valid():
            complication = complication_form.save(commit=False)
            try:
                medical_activity = patient.medical_activity
            except MedicalActivity.DoesNotExist:
                logger.warning("No MedicalActivity for patient %s, creating one", patient)
                medical_activity = MedicalActivity.objects.create(
                    patient=patient,
                    created_at=patient.entry_date
                )
            complication.medical_activity = medical_activity
            try:
                complication.save()
                logger.info("Complication saved for patient %s: %s", patient, complication)
                return redirect('patient_detail', pk=pk)
            except Exception as e:
                logger.error("Error saving complication: %s", str(e))
                complication_form.add_error(None, f"Error saving complication: {str(e)}")
        elif 'transplantation_submit' in request.POST and transplantation_form.is_valid():
            transplantation = transplantation_form.save(commit=False)
            try:
                medical_activity = patient.medical_activity
            except MedicalActivity.DoesNotExist:
                logger.warning("No MedicalActivity for patient %s, creating one", patient)
                medical_activity = MedicalActivity.objects.create(
                    patient=patient,
                    created_at=patient.entry_date
                )
            transplantation.medical_activity = medical_activity
            try:
                transplantation.save()
                logger.info("Transplantation saved for patient %s: %s", patient, transplantation)
                return redirect('patient_detail', pk=pk)
            except Exception as e:
                logger.error("Error saving transplantation: %s", str(e))
                transplantation_form.add_error(None, f"Error saving transplantation: {str(e)}")
        else:
            logger.warning("Forms invalid: session_form=%s, disease_form=%s, complication_form=%s, transplantation_form=%s", 
                          session_form.errors, disease_form.errors, complication_form.errors, transplantation_form.errors)
    else:
        session_form = HemodialysisSessionForm(center=center, prefix='session')
        disease_form = TransmittableDiseaseForm(center=center, prefix='disease')
        complication_form = ComplicationsForm(center=center, prefix='complication')
        transplantation_form = TransplantationForm(center=center, prefix='transplantation')

    if not is_submitter(request.user):
        session_form.fields['type'].disabled = True
        session_form.fields['method'].disabled = True
        session_form.fields['date_of_session'].disabled = True
        session_form.fields['responsible_doc'].disabled = True
        disease_form.fields['disease'].disabled = True
        disease_form.fields['date_of_contraction'].disabled = True
        complication_form.fields['complication'].disabled = True
        complication_form.fields['notes'].disabled = True
        complication_form.fields['date_of_contraction'].disabled = True
        transplantation_form.fields['transplantation'].disabled = True
        transplantation_form.fields['date_operation'].disabled = True
        transplantation_form.fields['notes'].disabled = True
    
    return render(request, 'centers/patient_detail.html', {
        'center': center,
        'patient': patient,
        'session_form': session_form,
        'disease_form': disease_form,
        'complication_form': complication_form,
        'transplantation_form': transplantation_form,
    })

@login_required
def center_users_list(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for center_users_list")
        return render(request, 'centers/404.html', status=404)
    if not is_viewer(request.user):
        logger.warning("Permission denied for user %s in center %s", request.user.username, center.label)
        return HttpResponse("Permission denied.", status=403)

    admin_staff = AdministrativeStaff.objects.filter(center=center)
    worker_staff = WorkerStaff.objects.filter(center=center)
    technical_staff = TechnicalStaff.objects.filter(center=center)
    medical_staff = MedicalStaff.objects.filter(center=center)
    paramedical_staff = ParamedicalStaff.objects.filter(center=center)

    staff_list = []
    for staff in admin_staff:
        staff_list.append({
            'id': staff.id,
            'type': 'Administrative',
            'nom': staff.nom,
            'prenom': staff.prenom,
            'role': staff.get_role_display(),
            'specific_field': staff.job_title,
            'specific_field_label': 'Job Title',
            'user': staff.user
        })
    for staff in worker_staff:
        staff_list.append({
            'id': staff.id,
            'type': 'Worker',
            'nom': staff.nom,
            'prenom': staff.prenom,
            'role': staff.get_role_display(),
            'specific_field': staff.job_title,
            'specific_field_label': 'Job Title',
            'user': staff.user
        })
    for staff in technical_staff:
        staff_list.append({
            'id': staff.id,
            'type': 'Technical',
            'nom': staff.nom,
            'prenom': staff.prenom,
            'role': staff.get_role_display(),
            'specific_field': staff.qualification,
            'specific_field_label': 'Qualification',
            'user': staff.user
        })
    for staff in medical_staff:
        staff_list.append({
            'id': staff.id,
            'type': 'Medical',
            'nom': staff.nom,
            'prenom': staff.prenom,
            'role': staff.get_role_display(),
            'specific_field': staff.cnom,
            'specific_field_label': 'CNOM',
            'user': staff.user
        })
    for staff in paramedical_staff:
        staff_list.append({
            'id': staff.id,
            'type': 'Paramedical',
            'nom': staff.nom,
            'prenom': staff.prenom,
            'role': staff.get_role_display(),
            'specific_field': staff.qualification,
            'specific_field_label': 'Qualification',
            'user': staff.user
        })

    logger.debug("User %s accessed staff list for center %s. Staff count: %s",
                 request.user.username, center.label, len(staff_list))

    context = {
        'center': center,
        'staff_list': staff_list,
        'is_local_admin': is_local_admin(request.user),
    }
    return render(request, 'centers/list_center_users.html', context)

@user_passes_test(is_local_admin)
def delete_staff(request, staff_id):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for delete_staff")
        return render(request, 'centers/404.html', status=404)

    if request.method != 'POST':
        logger.warning("Invalid method for delete_staff by user %s in center %s",
                       request.user.username, center.label)
        return HttpResponse("Method not allowed.", status=405)

    staff = None
    model = None
    for model_class in [AdministrativeStaff, WorkerStaff, TechnicalStaff, MedicalStaff, ParamedicalStaff]:
        try:
            staff = model_class.objects.get(id=staff_id, center=center)
            model = model_class.__name__
            break
        except model_class.DoesNotExist:
            continue

    if not staff:
        logger.error("Staff ID %s not found in center %s", staff_id, center.label)
        return render(request, 'centers/error.html', {
            'message': 'Staff member not found.'
        }, status=404)

    if staff.user == request.user:
        logger.warning("User %s attempted to delete themselves in center %s",
                       request.user.username, center.label)
        return render(request, 'centers/error.html', {
            'message': 'You cannot delete your own account.'
        }, status=403)

    user = staff.user
    try:
        staff.delete()
        if user:
            user.delete()
        logger.info("Deleted staff ID %s (%s) and user %s from center %s by %s",
                    staff_id, model, user.username if user else 'no user', center.label, request.user.username)
        return redirect('center_users_list')
    except Exception as e:
        logger.error("Failed to delete staff ID %s in center %s: %s", staff_id, center.label, str(e))
        return render(request, 'centers/error.html', {
            'message': f'Failed to delete staff member: {str(e)}'
        }, status=500)

@user_passes_test(is_local_admin)
def add_transplantation_ref(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for add_transplantation_ref")
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = TransplantationRefForm(request.POST)
        if form.is_valid():
            form.save()
            logger.info("TransplantationRef saved: %s", form.cleaned_data['label_transplantation'])
            return redirect('center_detail')
        else:
            logger.warning("TransplantationRef form is invalid: %s", form.errors)
    else:
        form = TransplantationRefForm()
    return render(request, 'centers/add_transplantation_ref.html', {
        'form': form,
        'center': center
    })


#=====================================APIS===================================

@method_decorator(csrf_exempt, name='dispatch')
class CenterLoginAPIView(APIView):
    def post(self, request):
        logger.debug("Received POST request to CenterLoginAPIView. CSRF exempt: %s", request.META.get('CSRF_COOKIE') is None)
        
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for API login request")
            return Response(
                {"error": "Invalid center subdomain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            logger.warning("Missing username or password in API login request")
            return Response(
                {"error": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            logger.warning("Failed login attempt for username: %s at center %s", username, tenant.label)
            return Response(
                {"error": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Handle superadmin
        if user.is_superuser:
            logger.info("Superadmin %s logging in to center %s", username, tenant.label)
            try:
                profile = user.verification_profile
                tokens = self.get_tokens_for_user(user)
                logger.info("Superadmin %s logged in for center %s (verification bypassed)", username, tenant.label)
                return Response({
                    "access": tokens["access"],
                    "refresh": tokens["refresh"],
                    "role": "SUPERADMIN",
                    "center": tenant.label
                }, status=status.HTTP_200_OK)
            except UserProfile.DoesNotExist:
                logger.error("No verification profile for superadmin %s", username)
                return Response(
                    {"error": "Verification profile missing. Contact support."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Handle non-superadmin users
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
                profile = user.verification_profile
                if not profile.is_verified:
                    logger.info("User %s requires email verification", username)
                    return Response(
                        {"error": "Email verification required.", "redirect": "verify_email"},
                        status=status.HTTP_403_FORBIDDEN
                    )
                tokens = self.get_tokens_for_user(user)
                logger.info("User %s logged in for center %s as %s", username, tenant.label, staff.__class__.__name__)
                return Response({
                    "access": tokens["access"],
                    "refresh": tokens["refresh"],
                    "role": staff_role,
                    "center": tenant.label
                }, status=status.HTTP_200_OK)
            except UserProfile.DoesNotExist:
                logger.error("No verification profile for user %s", username)
                return Response(
                    {"error": "Verification profile missing. Contact support."},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            logger.warning("User %s not authorized for center %s", username, tenant.label)
            return Response(
                {"error": "You are not authorized for this center."},
                status=status.HTTP_403_FORBIDDEN
            )

    def get_tokens_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }
    

@method_decorator(csrf_exempt, name='dispatch')
class AddAdministrativeStaffAPIView(APIView):
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.debug("Received POST request to AddMedicalStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add medical staff request")
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
        form = MedicalStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("Medical staff %s %s (ID: %s) added by %s in center %s",
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
                logger.error("Error saving medical staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Medical staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

@method_decorator(csrf_exempt, name='dispatch')
class AddParamedicalStaffAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.debug("Received POST request to AddParamedicalStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add paramedical staff request")
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
        form = ParamedicalStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("Paramedical staff %s %s (ID: %s) added by %s in center %s",
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
                logger.error("Error saving paramedical staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Paramedical staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

@method_decorator(csrf_exempt, name='dispatch')
class AddWorkerStaffAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.debug("Received POST request to AddWorkerStaffAPIView. User: %s", request.user.username)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add worker staff request")
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
        form = WorkerStaffForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    staff = form.save(commit=True)
                    logger.info("Worker staff %s %s (ID: %s) added by %s in center %s",
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
                logger.error("Error saving worker staff: %s", str(e))
                return Response(
                    {"error": f"Failed to save staff: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            logger.warning("Worker staff form invalid: %s", form.errors)
            return Response(
                {
                    "error": "Form validation failed.",
                    "errors": form.errors.as_data()
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
@method_decorator(csrf_exempt, name='dispatch')
class AddPatientAPIView(APIView):
    permission_classes = [IsAuthenticated]

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

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response(
                {"error": "Permission denied. Only local admins can add patients."},
                status=status.HTTP_403_FORBIDDEN
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
        
@method_decorator(csrf_exempt, name='dispatch')
class DeclareDeceasedAPIView(APIView):
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

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

        # Check if patient exists and belongs to the center
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response(
                {"error": "Patient not found or does not belong to this center."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Prepare form data
        form_data = request.data.copy()
        form_data['patient'] = patient_id

        # Validate and save form
        form = HemodialysisSessionForm(form_data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    session = form.save(commit=False)
                    session.patient = patient
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
    permission_classes = [IsAuthenticated]

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

@method_decorator(csrf_exempt, name='dispatch')
class AddComplicationsRefAPIView(APIView):
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logger.debug("MACHINE: Received POST request to AddMachineAPIView. User: %s, Data: %s",
                    request.user.username, request.data)

        # Check tenant
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("MACHINE: No tenant found")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)

        # Check LOCAL_ADMIN permission
        if not is_local_admin(request.user):
            logger.warning("MACHINE: Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can add machines."}, status=status.HTTP_403_FORBIDDEN)

        # Validate and save form
        form = MachineForm(request.data, center=tenant)
        if form.is_valid():
            try:
                with transaction.atomic():
                    machine = form.save(commit=False)
                    machine.center = tenant
                    logger.debug("MACHINE: Machine before save: brand=%s, center=%s, membrane=%s, filtre=%s",
                                machine.brand, machine.center_id,
                                machine.membrane_id if machine.membrane else 'None',
                                machine.filtre_id if machine.filtre else 'None')
                    machine.save()
                    logger.info("MACHINE: Machine (ID: %s, Brand: %s) added by %s in center %s",
                               machine.id, machine.brand, request.user.username, tenant.label)
                    return Response(
                        {
                            "success": "Machine added successfully.",
                            "machine_id": machine.id
                        },
                        status=status.HTTP_201_CREATED
                    )
            except Exception as e:
                logger.error("MACHINE: Error saving machine: %s", str(e))
                return Response({"error": f"Failed to save machine: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            logger.warning("MACHINE: Machine form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=status.HTTP_400_BAD_REQUEST)
        
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
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            patients = Patient.objects.filter(center=center).select_related('cnam').values(
                'id', 'nom', 'prenom', 'cin', 'weight', 'age', 'cnam__number', 'status',
                'entry_date', 'previously_dialysed', 'date_first_dia', 'blood_type', 'gender'
            )
            return Response(list(patients))
        except ObjectDoesNotExist:
            return Response({
                'error': 'Center not found for this tenant.'
            }, status=404)

class PatientMedicalActivityView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

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

class PatientsView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            center = Center.objects.get(sub_domain=request.tenant.sub_domain)
            patients = Patient.objects.filter(center=center).select_related('cnam').values(
                'id', 'nom', 'prenom', 'cin', 'weight', 'age', 'cnam__number', 'status',
                'entry_date', 'previously_dialysed', 'date_first_dia', 'blood_type', 'gender'
            )
            return Response(list(patients))
        except ObjectDoesNotExist:
            return Response({
                'error': 'Center not found for this tenant.'
            }, status=404)

class PatientDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, patient_id):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant provided for PatientDetailAPIView")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)

        if not is_viewer(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied."}, status=403)

        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
            hemodialysis_sessions = HemodialysisSession.objects.filter(medical_activity__patient=patient).values(
                'id', 'type__name', 'method__name', 'date_of_session', 'responsible_doc__nom', 'responsible_doc__prenom'
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
            logger.debug("Patient fetched: %s for center %s", patient, tenant.label)
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
                'date_first_dia': patient.date_first_dia,
                'blood_type': patient.blood_type,
                'gender': patient.gender,
                'hemodialysis_sessions': list(hemodialysis_sessions),
                'transmittable_diseases': list(diseases),
                'complications': list(complications),
                'transplantations': list(transplantations),
            })
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        

@method_decorator(csrf_exempt, name='dispatch')
class DeclareDeceasedAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, patient_id):
        logger.debug("Received POST request to DeclareDeceasedAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for declare deceased request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        if not is_local_admin(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only local admins can declare patients deceased."}, status=403)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        form_data = request.data.copy()
        form = DeceasePatientForm(form_data, instance=patient)
        if form.is_valid():
            try:
                with transaction.atomic():
                    patient = form.save(commit=False)
                    patient.status = 'DECEASED'
                    patient.save()
                    logger.info("Patient %s %s (ID: %s) declared deceased by %s in center %s",
                               patient.nom, patient.prenom, patient.id, request.user.username, tenant.label)
                    return Response({"success": "Patient declared deceased.", "patient_id": patient.id}, status=200)
            except Exception as e:
                logger.error("Error declaring patient deceased: %s", str(e))
                return Response({"error": f"Failed to declare patient deceased: {str(e)}"}, status=400)
        else:
            logger.warning("Decease patient form invalid: %s", form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=400)

class PatientMedicalActivityView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddHemodialysisSessionAPIView for patient ID: %s. User: %s",
                    patient_id, request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add hemodialysis session request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        if not is_submitter(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only submitters can add hemodialysis sessions."}, status=403)
        try:
            patient = Patient.objects.get(id=patient_id, center=tenant)
        except Patient.DoesNotExist:
            logger.error("Patient ID %s not found in center %s", patient_id, tenant.label)
            return Response({"error": "Patient not found or does not belong to this center."}, status=404)
        form_data = request.data.copy()
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
                        "patient_id": patient_id
                    }, status=201)
            except Exception as e:
                logger.error("Error saving hemodialysis session for patient ID %s: %s", patient_id, str(e))
                return Response({"error": f"Failed to save hemodialysis session: {str(e)}"}, status=400)
        else:
            logger.warning("Hemodialysis session form invalid for patient ID %s: %s", patient_id, form.errors)
            return Response({"error": "Form validation failed.", "errors": form.errors.as_data()}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class AddTransmittableDiseaseAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddTransmittableDiseaseAPIView for patient ID: %s. User: %s, Data: %s",
                     patient_id, request.user.username, request.data)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add transmittable disease request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        if not is_submitter(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only submitters can add transmittable diseases."}, status=403)
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
                        ref_form = TransmittableDiseaseRefForm({
                            'label_disease': form.cleaned_data['new_disease_name'],
                            'type_of_transmission': form_data.get('type_of_transmission', 'Unknown')
                        })
                        if ref_form.is_valid():
                            disease_ref = ref_form.save()
                            disease.disease = disease_ref
                        else:
                            logger.warning("TransmittableDiseaseRef form invalid: %s", ref_form.errors)
                            return Response({"error": "Invalid new disease name.", "errors": ref_form.errors.as_data()}, status=400)
                    disease.center = tenant
                    try:
                        disease.medical_activity = patient.medical_activity
                    except MedicalActivity.DoesNotExist:
                        disease.medical_activity = MedicalActivity.objects.create(patient=patient, created_at=patient.entry_date)
                    disease.save()
                    logger.info("Transmittable disease (ID: %s) added for patient %s %s by %s in center %s",
                               disease.id, patient.nom, patient.prenom, request.user.username, tenant.label)
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

@method_decorator(csrf_exempt, name='dispatch')
class AddComplicationsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddComplicationsAPIView for patient ID: %s. User: %s, Data: %s",
                     patient_id, request.user.username, request.data)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add complications request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        if not is_submitter(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only submitters can add complications."}, status=403)
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
                    complication.center = tenant
                    try:
                        complication.medical_activity = patient.medical_activity
                    except MedicalActivity.DoesNotExist:
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

@method_decorator(csrf_exempt, name='dispatch')
class AddTransplantationAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, patient_id):
        logger.debug("Received POST request to AddTransplantationAPIView for patient ID: %s. User: %s, Data: %s",
                     patient_id, request.user.username, request.data)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for add transplantation request")
            return Response({"error": "Invalid or missing center subdomain."}, status=400)
        if not is_submitter(request.user):
            logger.warning("Permission denied for user %s in center %s", request.user.username, tenant.label)
            return Response({"error": "Permission denied. Only submitters can add transplantations."}, status=403)
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
                    transplantation.center = tenant
                    try:
                        transplantation.medical_activity = patient.medical_activity
                    except MedicalActivity.DoesNotExist:
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
class MedicalStaffAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        type_hemos = TypeHemo.objects.all().values('id', 'name')
        return Response(list(type_hemos))

class MethodHemoAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        diseases = TransmittableDiseaseRef.objects.all().values('id', 'label_disease', 'type_of_transmission')
        return Response(list(diseases))

class ComplicationsRefAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        complications = ComplicationsRef.objects.all().values('id', 'label_complication')
        return Response(list(complications))

class TransplantationRefAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        transplantations = TransplantationRef.objects.all().values('id', 'label_transplantation')
        return Response(list(transplantations))
@method_decorator(csrf_exempt, name='dispatch')
class CNAMListAPIView(APIView):
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("Received GET request to AdministrativeStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list administrative staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = AdministrativeStaff.objects.filter(center=tenant)
            data = [
                {
                    'id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'job_title': s.job_title
                } for s in staff
            ]
            logger.info("Fetched %d administrative staff for center %s", len(data), tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching administrative staff: %s", str(e))
            return Response({"error": f"Failed to fetch administrative staff: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class MedicalStaffListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("Received GET request to MedicalStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list medical staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = MedicalStaff.objects.filter(center=tenant)
            data = [
                {
                    'id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'cnom': s.cnom
                } for s in staff
            ]
            logger.info("Fetched %d medical staff for center %s", len(data), tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching medical staff: %s", str(e))
            return Response({"error": f"Failed to fetch medical staff: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class ParamedicalStaffListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("Received GET request to ParamedicalStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list paramedical staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = ParamedicalStaff.objects.filter(center=tenant)
            data = [
                {
                    'id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'qualification': s.qualification
                } for s in staff
            ]
            logger.info("Fetched %d paramedical staff for center %s", len(data), tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching paramedical staff: %s", str(e))
            return Response({"error": f"Failed to fetch paramedical staff: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class TechnicalStaffListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("Received GET request to TechnicalStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list technical staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = TechnicalStaff.objects.filter(center=tenant)
            data = [
                {
                    'id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'qualification': s.qualification
                } for s in staff
            ]
            logger.info("Fetched %d technical staff for center %s", len(data), tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching technical staff: %s", str(e))
            return Response({"error": f"Failed to fetch technical staff: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')
class WorkerStaffListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("Received GET request to WorkerStaffListAPIView. User: %s", request.user.username)
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("No tenant found for list worker staff request")
            return Response({"error": "Invalid or missing center subdomain."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            staff = WorkerStaff.objects.filter(center=tenant)
            data = [
                {
                    'id': s.id,
                    'nom': s.nom,
                    'prenom': s.prenom,
                    'cin': s.cin,
                    'role': s.role,
                    'job_title': s.job_title
                } for s in staff
            ]
            logger.info("Fetched %d worker staff for center %s", len(data), tenant.label)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error("Error fetching worker staff: %s", str(e))
            return Response({"error": f"Failed to fetch worker staff: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class UpdateMedicalStaffAPIView(APIView):
    def put(self, request, pk):
        try:
            medical_staff = MedicalStaff.objects.get(pk=pk)
            user = medical_staff.user
        except MedicalStaff.DoesNotExist:
            logger.error(f"MedicalStaff with ID {pk} not found.")
            return Response({'error': 'Medical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        user_data = {
            'username': data.get('username', user.username),
            'email': data.get('email', user.email),
        }
        if 'password' in data and data['password']:
            user_data['password'] = data['password']
        user_serializer = UserSerializer(user, data=user_data, partial=True)
        if user_serializer.is_valid():
            user = user_serializer.save()
            if 'password' in user_data:
                user.set_password(user_data['password'])
                user.save()
        else:
            return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = MedicalStaffSerializer(medical_staff, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Medical staff {medical_staff.nom} {medical_staff.prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)
        logger.error(f"Failed to update MedicalStaff with ID {pk}: {serializer.errors}")
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class DeleteMedicalStaffAPIView(APIView):
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
    def put(self, request, pk):
        try:
            paramedical_staff = ParamedicalStaff.objects.get(pk=pk)
            user = paramedical_staff.user
        except ParamedicalStaff.DoesNotExist:
            logger.error(f"ParamedicalStaff with ID {pk} not found.")
            return Response({'error': 'Paramedical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        user_data = {
            'username': data.get('username', user.username),
            'email': data.get('email', user.email),
        }
        if 'password' in data and data['password']:
            user_data['password'] = data['password']
        user_serializer = UserSerializer(user, data=user_data, partial=True)
        if user_serializer.is_valid():
            user = user_serializer.save()
            if 'password' in user_data:
                user.set_password(user_data['password'])
                user.save()
        else:
            return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = ParamedicalStaffSerializer(paramedical_staff, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Paramedical staff {paramedical_staff.nom} {paramedical_staff.prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)
        logger.error(f"Failed to update ParamedicalStaff with ID {pk}: {serializer.errors}")
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class DeleteParamedicalStaffAPIView(APIView):
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
    def put(self, request, pk):
        try:
            admin_staff = AdministrativeStaff.objects.get(pk=pk)
            user = admin_staff.user
        except AdministrativeStaff.DoesNotExist:
            logger.error(f"AdministrativeStaff with ID {pk} not found.")
            return Response({'error': 'Administrative staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        user_data = {
            'username': data.get('username', user.username),
            'email': data.get('email', user.email),
        }
        if 'password' in data and data['password']:
            user_data['password'] = data['password']
        user_serializer = UserSerializer(user, data=user_data, partial=True)
        if user_serializer.is_valid():
            user = user_serializer.save()
            if 'password' in user_data:
                user.set_password(user_data['password'])
                user.save()
        else:
            return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = AdministrativeStaffSerializer(admin_staff, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Administrative staff {admin_staff.nom} {admin_staff.prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)
        logger.error(f"Failed to update AdministrativeStaff with ID {pk}: {serializer.errors}")
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class DeleteAdministrativeStaffAPIView(APIView):
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
    def put(self, request, pk):
        try:
            worker_staff = WorkerStaff.objects.get(pk=pk)
            user = worker_staff.user
        except WorkerStaff.DoesNotExist:
            logger.error(f"WorkerStaff with ID {pk} not found.")
            return Response({'error': 'Worker staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        user_data = {
            'username': data.get('username', user.username),
            'email': data.get('email', user.email),
        }
        if 'password' in data and data['password']:
            user_data['password'] = data['password']
        user_serializer = UserSerializer(user, data=user_data, partial=True)
        if user_serializer.is_valid():
            user = user_serializer.save()
            if 'password' in user_data:
                user.set_password(user_data['password'])
                user.save()
        else:
            return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = WorkerStaffSerializer(worker_staff, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Worker staff {worker_staff.nom} {worker_staff.prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)
        logger.error(f"Failed to update WorkerStaff with ID {pk}: {serializer.errors}")
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class DeleteWorkerStaffAPIView(APIView):
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
    def put(self, request, pk):
        try:
            technical_staff = TechnicalStaff.objects.get(pk=pk)
            user = technical_staff.user
        except TechnicalStaff.DoesNotExist:
            logger.error(f"TechnicalStaff with ID {pk} not found.")
            return Response({'error': 'Technical staff not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        user_data = {
            'username': data.get('username', user.username),
            'email': data.get('email', user.email),
        }
        if 'password' in data and data['password']:
            user_data['password'] = data['password']
        user_serializer = UserSerializer(user, data=user_data, partial=True)
        if user_serializer.is_valid():
            user = user_serializer.save()
            if 'password' in user_data:
                user.set_password(user_data['password'])
                user.save()
        else:
            return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer = TechnicalStaffSerializer(technical_staff, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Technical staff {technical_staff.nom} {technical_staff.prenom} (ID: {pk}) updated by {request.user.username}.")
            return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)
        logger.error(f"Failed to update TechnicalStaff with ID {pk}: {serializer.errors}")
        return Response({'error': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

class DeleteTechnicalStaffAPIView(APIView):
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