import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from reportlab.pdfgen import canvas
from io import BytesIO

from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, Delegation, Patient, CNAM, MethodHemo, MedicalActivity, TransmittableDiseaseRef, ComplicationsRef
from .forms import CenterForm, TechnicalStaffForm, MedicalStaffForm, ParamedicalStaffForm, MachineForm, PatientForm, HemodialysisSessionForm, TransmittableDiseaseForm, TransmittableDiseaseRefForm, ComplicationsForm, ComplicationsRefForm

logger = logging.getLogger(__name__)

def add_center(request):
    center_id = request.GET.get('center_id')
    instance = get_object_or_404(Center, pk=center_id) if center_id else None
    if request.method == 'POST':
        form = CenterForm(request.POST, instance=instance)
        logger.debug("POST data: %s", request.POST)
        if form.is_valid():
            logger.info("Form is valid, cleaned data: %s", form.cleaned_data)
            try:
                center = form.save()
                logger.info("Center saved: %s, Delegation: %s", center, center.delegation)
                # Redirect to superadmin_center_detail for super admin, subdomain for center users
                if not request.tenant:
                    return redirect('superadmin_center_detail', pk=center.pk)
                return redirect(f"http://{center.sub_domain | default:'center1'}.localhost:8000/")
            except Exception as e:
                logger.error("Error saving center: %s", str(e))
                form.add_error(None, f"Error saving center: {str(e)}")
        else:
            logger.warning("Form is invalid: %s", form.errors)
            return render(request, 'centers/add_center.html', {'form': form})
    else:
        form = CenterForm(instance=instance)
        logger.debug("Rendering form with instance: %s", instance)
    return render(request, 'centers/add_center.html', {'form': form})

def generate_report(request):
    center = request.tenant
    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()
    patients = center.patient_staff.all()
    return render(request, 'centers/report.html', {
        'center': center,
        'technical_staff': technical_staff,
        'medical_staff': medical_staff,
        'paramedical_staff': paramedical_staff,
        'patients': patients,
    })

def export_pdf(request):
    center = request.tenant
    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()
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
        draw_line(f"- {patient.nom} {staff.prenom} (CNAM: {patient.cnam.number}, Status: {patient.status})", x=120)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="report.pdf"'
    })

def center_detail(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    return render(request, 'centers/center_detail.html', {
        'center': center,
        'technical_staff': center.technicalstaff_staff.all(),
        'medical_staff': center.medicalstaff_staff.all(),
        'paramedical_staff': center.paramedicalstaff_staff.all(),
        'patients': center.patient_staff.all(),
    })

def add_machine(request):
    if not hasattr(request, 'tenant') or not request.tenant:
        logger.error("No tenant provided for add_machine")
        return render(request, 'centers/error.html', {'message': 'No center selected. Please access via a valid tenant.'}, status=400)
    center = request.tenant
    if not isinstance(center, Center):
        logger.error("Invalid tenant type: %s", type(center))
        return render(request, 'centers/error.html', {'message': 'Invalid center configuration.'}, status=400)
    if request.method == 'POST':
        form = MachineForm(request.POST, center=center)
        if form.is_valid():
            machine = form.save()
            logger.info("Machine saved: %s for center %s", machine, center)
            return redirect('center_detail')
        else:
            logger.warning("Machine form is invalid: %s", form.errors)
    else:
        form = MachineForm(center=center)
    return render(request, 'centers/add_machine.html', {'form': form, 'center': center})

def add_technical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = TechnicalStaffForm(request.POST, center=center)
        if form.is_valid():
            form.save()
            return redirect('center_detail')
    else:
        form = TechnicalStaffForm(center=center)
    return render(request, 'centers/add_technical_staff.html', {
        'form': form,
        'center': center
    })

def add_medical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = MedicalStaffForm(request.POST, center=center)
        if form.is_valid():
            form.save()
            return redirect('center_detail')
    else:
        form = MedicalStaffForm(center=center)
    return render(request, 'centers/add_medical_staff.html', {
        'form': form,
        'center': center
    })

def add_paramedical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = ParamedicalStaffForm(request.POST, center=center)
        if form.is_valid():
            form.save()
            return redirect('center_detail')
    else:
        form = ParamedicalStaffForm(center=center)
    return render(request, 'centers/add_paramedical_staff.html', {
        'form': form,
        'center': center
    })

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

def list_centers(request):
    if hasattr(request, 'tenant') and request.tenant:
        return redirect('center_detail')
    centers = Center.objects.all().order_by('label')
    return render(request, 'centers/list_centers.html', {
        'centers': centers
    })

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

def list_patients(request):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for list_patients")
        return render(request, 'centers/404.html', status=404)
    patients = center.patient_staff.all()
    logger.debug("Patients fetched for center %s: %s", center.label, list(patients.values('nom', 'prenom')))
    return render(request, 'centers/list_patients.html', {
        'center': center,
        'patients': patients,
    })

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

def patient_detail(request, pk):
    center = request.tenant
    if not center:
        logger.error("No tenant provided for patient_detail")
        return render(request, 'centers/404.html', status=404)
    patient = get_object_or_404(Patient, pk=pk, center=center)
    logger.debug("Patient fetched: %s for center %s", patient, center.label)
    
    if request.method == 'POST':
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
    
    return render(request, 'centers/patient_detail.html', {
        'center': center,
        'patient': patient,
        'session_form': session_form,
        'disease_form': disease_form,
        'complication_form': complication_form,
    })

def superadmin_center_detail(request, pk):
    center = get_object_or_404(Center, pk=pk)
    return render(request, 'centers/superadmin_center_detail.html', {
        'center': center,
        'technical_staff': center.technicalstaff_staff.all(),
        'medical_staff': center.medicalstaff_staff.all(),
        'paramedical_staff': center.paramedicalstaff_staff.all(),
        'patients': center.patient_staff.all(),
    })