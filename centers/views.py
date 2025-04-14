from django.shortcuts import render, redirect
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from io import BytesIO

from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff
from .forms import CenterForm, TechnicalStaffForm, MedicalStaffForm, ParamedicalStaffForm

# Create a new Center
def add_center(request):
    if request.method == 'POST':
        form = CenterForm(request.POST)
        if form.is_valid():
            center = form.save()
            return redirect(f"http://{center.sub_domain}.localhost:8000/")
    else:
        form = CenterForm()
    return render(request, 'centers/add_center.html', {'form': form})


# Generate a human-readable HTML report
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


# Export report as PDF
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
    draw_line(f"Dénomination: {center.nom}")
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


# View to show current Center and staff details
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


# Add staff (technical, medical, paramedical) to current Center
def add_staff(request):
    center = request.tenant
    if not center:
        return render(request, 'centers/404.html', status=404)

    if request.method == 'POST':
        tech_form = TechnicalStaffForm(request.POST, prefix='tech')
        med_form = MedicalStaffForm(request.POST, prefix='med')
        para_form = ParamedicalStaffForm(request.POST, prefix='para')

        if tech_form.is_valid():
            staff = tech_form.save(commit=False)
            staff.center = center
            staff.save()

        if med_form.is_valid():
            staff = med_form.save(commit=False)
            staff.center = center
            staff.save()

        if para_form.is_valid():
            staff = para_form.save(commit=False)
            staff.center = center
            staff.save()

        return redirect('center_detail')

    context = {
        'center': center,
        'tech_form': TechnicalStaffForm(prefix='tech'),
        'med_form': MedicalStaffForm(prefix='med'),
        'para_form': ParamedicalStaffForm(prefix='para'),
    }
    return render(request, 'centers/add_staff.html', context)
