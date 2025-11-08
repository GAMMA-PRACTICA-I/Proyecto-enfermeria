from django import forms
from .models import ComentarioFicha


class StudentGeneralForm(forms.Form):
    nombre_legal = forms.CharField(required=False, max_length=120)
    genero = forms.CharField(required=False, max_length=20)
    rut = forms.CharField(required=False, max_length=20)
    fecha_nacimiento = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    telefono_celular = forms.CharField(required=False, max_length=30)
    direccion_actual = forms.CharField(required=False, widget=forms.Textarea)
    direccion_origen = forms.CharField(required=False, widget=forms.Textarea)
    contacto_emergencia_nombre = forms.CharField(required=False, max_length=120)
    contacto_emergencia_parentesco = forms.CharField(required=False, max_length=80)
    contacto_emergencia_telefono = forms.CharField(required=False, max_length=30)
    centro_salud = forms.CharField(required=False, max_length=120)
    prevision = forms.CharField(required=False, max_length=20)        # se mapea a 'seguro' en la vista
    prevision_detalle = forms.CharField(required=False, max_length=120)
    correo_institucional = forms.EmailField(required=False)
    foto_ficha = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/png"})
    )


class StudentAcademicForm(forms.Form):
    nombre_social = forms.CharField(required=False, max_length=120)
    carrera = forms.CharField(required=False, max_length=120)
    anio_cursa = forms.IntegerField(required=False, min_value=1, max_value=10)
    estado = forms.CharField(required=False, max_length=50)
    asignatura = forms.CharField(required=False, max_length=160)
    correo_personal = forms.EmailField(required=False)


class StudentMedicalForm(forms.Form):
    alergias = forms.CharField(required=False, widget=forms.Textarea)
    grupo_sanguineo = forms.CharField(required=False, max_length=3)
    enfermedades_cronicas = forms.CharField(required=False, widget=forms.Textarea)
    medicamentos_diarios = forms.CharField(required=False, widget=forms.Textarea)
    otros_antecedentes = forms.CharField(required=False, widget=forms.Textarea)


class StudentVaccinesForm(forms.Form):
    varicela_serologia_resultado = forms.CharField(required=False, max_length=15)
    varicela_serologia_fecha = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    influenza_fecha = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    vacunas_obs = forms.CharField(required=False)


class StudentDeclarationForm(forms.Form):
    decl_nombre = forms.CharField(required=False, max_length=120)
    decl_rut = forms.CharField(required=False, max_length=20)
    decl_fecha = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    decl_firma = forms.CharField(required=False, max_length=255)

from django import forms
from .models import ComentarioDocumento


class ComentarioDocumentoForm(forms.ModelForm):
    class Meta:
        model = ComentarioDocumento
        fields = ["mensaje"]  # <-- este es el campo del comentario

        widgets = {
            "mensaje": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Escribe un comentario..."
            })
        }

class ComentarioFichaForm(forms.ModelForm):
    class Meta:
        model = ComentarioFicha
        fields = ["mensaje"]
        widgets = {
            "mensaje": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Escribe un comentario para toda la ficha..."
            })
        }
