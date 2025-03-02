from django.shortcuts import render, redirect, get_object_or_404
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from io import BytesIO
from .forms import CenterForm, TechnicalStaffForm, MedicalStaffForm, ParamedicalStaffForm

# View to create a new Center
def add_center(request):
    if request.method == 'POST':
        form = CenterForm(request.POST)
        if form.is_valid():
            center = form.save()
            # Redirect to the subdomain URL after creating a Center
            return redirect(f"http://{center.sub_domain}.localhost:8000/")
    else:
        form = CenterForm()
    return render(request, 'centers/add_center.html', {'form': form})

def generate_report(request):
    # Get the current tenant (Center) from the middleware
    center = request.tenant

    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)

    # Fetch all staff members associated with this center
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()

    # Create the report content
    report_content = f"""
    République Tunisienne
    Ministère de la Santé
    Direction de la Réglementation et du Contrôle des Professions de Santé

    RAPPORT D'ACTIVITE MEDICALE
    DES CENTRES D'HEMODIALYSE
    Semestre: 2, Année: 2021

    I -- CARACTERISTIQUES DU CENTRE
    1 -- Coordonnées
    Dénomination: {center.nom}
    Adresse: {center.sub_domain}.localhost:8000
    Tél: {center.tel}

    II -- RESSOURCES HUMAINES
    1 -- Personnel Médical
    """

    # Add technical staff details
    report_content += "\nTechnical Staff:\n"
    for staff in technical_staff:
        report_content += f"- {staff.nom} {staff.prenom} ({staff.qualification})\n"

    # Add medical staff details
    report_content += "\nMedical Staff:\n"
    for staff in medical_staff:
        report_content += f"- {staff.nom} {staff.prenom} ({staff.cnom})\n"

    # Add paramedical staff details
    report_content += "\nParamedical Staff:\n"
    for staff in paramedical_staff:
        report_content += f"- {staff.nom} {staff.prenom} ({staff.qualification})\n"

    # Render the report in HTML with a button to export as PDF
    return render(request, 'centers/report.html', {
        'center': center,
        'technical_staff': technical_staff,
        'medical_staff': medical_staff,
        'paramedical_staff': paramedical_staff,
        'report_content': report_content,
    })

def export_pdf(request):
    # Get the current tenant (Center) from the middleware
    center = request.tenant

    if not center:
        return HttpResponse("No center found for this subdomain.", status=404)

    # Fetch all staff members associated with this center
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()

    # Create a PDF buffer
    buffer = BytesIO()

    # Create the PDF object
    pdf = canvas.Canvas(buffer)

    # Add content to the PDF
    pdf.drawString(100, 800, "République Tunisienne")
    pdf.drawString(100, 780, "Ministère de la Santé")
    pdf.drawString(100, 760, "Direction de la Réglementation et du Contrôle des Professions de Santé")
    pdf.drawString(100, 740, "RAPPORT D'ACTIVITE MEDICALE")
    pdf.drawString(100, 720, "DES CENTRES D'HEMODIALYSE")
    pdf.drawString(100, 700, f"Semestre: 2, Année: 2021")

    pdf.drawString(100, 680, "I -- CARACTERISTIQUES DU CENTRE")
    pdf.drawString(100, 660, f"Dénomination: {center.nom}")
    pdf.drawString(100, 640, f"Adresse: {center.sub_domain}.localhost:8000")
    pdf.drawString(100, 620, f"Tél: {center.tel}")

    pdf.drawString(100, 600, "II -- RESSOURCES HUMAINES")
    pdf.drawString(100, 580, "1 -- Personnel Médical")

    y = 560
    pdf.drawString(100, y, "Technical Staff:")
    for staff in technical_staff:
        y -= 20
        pdf.drawString(120, y, f"- {staff.nom} {staff.prenom} ({staff.qualification})")

    y -= 20
    pdf.drawString(100, y, "Medical Staff:")
    for staff in medical_staff:
        y -= 20
        pdf.drawString(120, y, f"- {staff.nom} {staff.prenom} ({staff.cnom})")

    y -= 20
    pdf.drawString(100, y, "Paramedical Staff:")
    for staff in paramedical_staff:
        y -= 20
        pdf.drawString(120, y, f"- {staff.nom} {staff.prenom} ({staff.qualification})")

    # Finalize the PDF
    pdf.showPage()
    pdf.save()

    # Get the PDF content and return it as a response
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="report.pdf"'
    return response

# View to display Center details (only for subdomains)
def center_detail(request):
    center = request.tenant  # Get the current tenant from the middleware

    if not center:
        return render(request, 'centers/404.html', status=404)  # Handle missing tenant

    # Get all staff members associated with this Center
    technical_staff = center.technicalstaff_staff.all()
    medical_staff = center.medicalstaff_staff.all()
    paramedical_staff = center.paramedicalstaff_staff.all()

    context = {
        'center': center,
        'technical_staff': technical_staff,
        'medical_staff': medical_staff,
        'paramedical_staff': paramedical_staff,
    }
    return render(request, 'centers/center_detail.html', context)

# View to add Staff for a Center (only for subdomains)
def add_staff(request):
    center = request.tenant  # Get the current tenant from the middleware

    if not center:
        return render(request, 'centers/404.html', status=404)  # Handle missing tenant

    if request.method == 'POST':
        tech_form = TechnicalStaffForm(request.POST)
        med_form = MedicalStaffForm(request.POST)
        para_form = ParamedicalStaffForm(request.POST)

        if tech_form.is_valid():
            tech = tech_form.save(commit=False)
            tech.center = center
            tech.save()

        if med_form.is_valid():
            med = med_form.save(commit=False)
            med.center = center
            med.save()

        if para_form.is_valid():
            para = para_form.save(commit=False)
            para.center = center
            para.save()

        return redirect('center_detail')  # Redirect to the tenant's detail page

    else:
        tech_form = TechnicalStaffForm()
        med_form = MedicalStaffForm()
        para_form = ParamedicalStaffForm()

    context = {
        'center': center,
        'tech_form': tech_form,
        'med_form': med_form,
        'para_form': para_form,
    }
    return render(request, 'centers/add_staff.html', context)