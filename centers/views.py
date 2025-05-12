import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth import authenticate, login
from reportlab.pdfgen import canvas
from io import BytesIO
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, Delegation, Patient, CNAM, MethodHemo, MedicalActivity, TransmittableDiseaseRef, ComplicationsRef
from .forms import TechnicalStaffForm, MedicalStaffForm, ParamedicalStaffForm, AdministrativeStaffForm, WorkerStaffForm, MachineForm, PatientForm, HemodialysisSessionForm, TransmittableDiseaseForm, TransmittableDiseaseRefForm, ComplicationsForm, ComplicationsRefForm

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
            # Reject superusers
            if user.is_superuser:
                logger.warning("Superadmin %s attempted login at center %s", username, tenant.label)
                return render(request, 'centers/login.html', {
                    'error': 'Superadmin accounts cannot log in to center portals.'
                })
            # Check all staff types for this center
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
                login(request, user)
                logger.info("User %s logged in for center %s as %s", username, tenant.label, staff.__class__.__name__)
                return redirect('center_detail')
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
def generate_report(request):
    center = request.tenant
    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)
    if not is_viewer(request.user):
        return HttpResponse("Permission denied.", status=403)
    technical_staff = center.technical_staff.all()
    medical_staff = center.medical_staff.all()
    paramedical_staff = center.paramedical_staff.all()
    patients = center.patient_staff.all()
    return render(request, 'centers/report.html', {
        'center': center,
        'technical_staff': technical_staff,
        'medical_staff': medical_staff,
        'paramedical_staff': paramedical_staff,
        'patients': patients,
    })

@login_required
def export_pdf(request):
    center = request.tenant
    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)
    if not is_viewer(request.user):
        return HttpResponse("Permission denied.", status=403)
    technical_staff = center.technical_staff.all()
    medical_staff = center.medical_staff.all()
    paramedical_staff = center.paramedical_staff.all()
    patients = center.patient_staff.all()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    def draw_line(text, x=100):
        nonlocal y
        pdf.drawString(x, y, text)
        y -= 20
    draw_line("République Tunisienne")
    draw_line("Ministère de la Santé")
    draw_line("Direction de la Réglementation et du Contrôle des Professions de Santé")
    draw_line("RAPPORT D'ACTIVITE MEDICALE")
    draw_line("DES CENTRES D'HEMODIALYSE")
    draw_line("Semestre: 2, Année: 2021")
    draw_line("")
    draw_line("I -- CARACTERISTIQUES DU CENTRE")
    draw_line(f"Dénomination: {center.label}")
    draw_line(f"Adresse: {center.sub_domain}.localhost:8000")
    draw_line(f"Tél: {center.tel}")
    draw_line("")
    draw_line("II -- RESSOURCES HUMAINES")
    draw_line("1 -- Personnel Technique:")
    for staff in technical_staff:
        draw_line(f"- {staff.nom} {staff.prenom} ({staff.qualification})", x=120)
    draw_line("2 -- Personnel Médical:")
    for staff in medical_staff:
        draw_line(f"- {staff.nom} {staff.prenom} ({staff.cnom})", x=120)
    draw_line("3 -- Personnel Paramédical:")
    for staff in paramedical_staff:
        draw_line(f"- {staff.nom} {staff.prenom} ({staff.qualification})", x=120)
    draw_line("4 -- Patients:")
    for patient in patients:
        draw_line(f"- {patient.nom} {patient.prenom} (CNAM: {patient.cnam.number}, Status: {patient.status})", x=120)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="report.pdf"'
    })

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
        else:
            logger.warning("Forms invalid: session_form=%s, disease_form=%s, complication_form=%s", 
                          session_form.errors, disease_form.errors, complication_form.errors)
    else:
        session_form = HemodialysisSessionForm(center=center, prefix='session')
        disease_form = TransmittableDiseaseForm(center=center, prefix='disease')
        complication_form = ComplicationsForm(center=center, prefix='complication')

    # Disable forms for non-submitters
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
    
    return render(request, 'centers/patient_detail.html', {
        'center': center,
        'patient': patient,
        'session_form': session_form,
        'disease_form': disease_form,
        'complication_form': complication_form,
    })