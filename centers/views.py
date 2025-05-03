import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from io import BytesIO

from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, Delegation
from .forms import CenterForm, TechnicalStaffForm, MedicalStaffForm, ParamedicalStaffForm,MachineForm

logger = logging.getLogger(__name__)

def add_center(request):
    if request.method == 'POST':
        form = CenterForm(request.POST)
        logger.debug("POST data: %s", request.POST)
        if form.is_valid():
            logger.info("Form is valid, cleaned data: %s", form.cleaned_data)
            try:
                center = form.save()
                logger.info("Center saved: %s, Delegation: %s", center, center.delegation)
                return redirect(f"http://{center.sub_domain}.localhost:8000/")
            except Exception as e:
                logger.error("Error saving center: %s", str(e))
                form.add_error(None, f"Error saving center: {str(e)}")
        else:
            logger.warning("Form is invalid: %s", form.errors)
            # Ensure errors are passed to template
            return render(request, 'centers/add_center.html', {'form': form})
    else:
        form = CenterForm()
        logger.debug("Rendering empty form")
    return render(request, 'centers/add_center.html', {'form': form})

def generate_report(request):
    center = request.tenant
    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()
    return render(request, 'centers/report.html', {
        'center': center,
        'technical_staff': technical_staff,
        'medical_staff': medical_staff,
        'paramedical_staff': paramedical_staff,
    })

def export_pdf(request):
    center = request.tenant
    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()
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
        form = TechnicalStaffForm(request.POST)
        if form.is_valid():
            staff = form.save(commit=False)
            staff.center = center
            staff.save()
            return redirect('center_detail')
    else:
        form = TechnicalStaffForm()
    return render(request, 'centers/add_technical_staff.html', {
        'form': form,
        'center': center
    })

def add_medical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = MedicalStaffForm(request.POST)
        if form.is_valid():
            staff = form.save(commit=False)
            staff.center = center
            staff.save()
            return redirect('center_detail')
    else:
        form = MedicalStaffForm()
    return render(request, 'centers/add_medical_staff.html', {
        'form': form,
        'center': center
    })

def add_paramedical_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)
    if request.method == 'POST':
        form = ParamedicalStaffForm(request.POST)
        if form.is_valid():
            staff = form.save(commit=False)
            staff.center = center
            staff.save()
            return redirect('center_detail')
    else:
        form = ParamedicalStaffForm()
    return render(request, 'centers/add_paramedical_staff.html', {
        'form': form,
        'center': center
    })

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