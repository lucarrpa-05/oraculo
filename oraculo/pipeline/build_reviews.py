# -*- coding: utf-8 -*-
"""
Curated Medicina (ME03) rotation reviews -> model/hospital_reviews.json

SOURCE: "Conectados Rotando" trimestrales 2026-1, recopiladas por la representacion
estudiantil de Medicina (Escuela de Medicina y Ciencias de la Salud, U. del Rosario) y
entregadas por la presidencia del consejo estudiantil. Cuatro reportes:
  - VII  Bloque Clinico I (Medicina Interna) + II (Cirugia General)  (22 estudiantes)
  - VIII Bloque Clinico III/IV (Pediatria, Neonatologia, Gineco, Psiquiatria, Neuro,
         Oftalmo, Otorrino)                                          (26 estudiantes)
  - IX   MSP 1 especialidades clinico-quirurgicas                    (20 estudiantes)
  - X    (encuesta cruda, rotaciones no hospitalarias: medicina legal, rural...) -> no
         se mapea a hospital, queda fuera de esta vista.

GRANULARITY (decision, antes diferida): la resena vive en el par (hospital x rotacion).
El hospital es la entidad principal (coincide con model/hospitals.json y con la decision
del estudiante: elegir bloque -> elegir hospital); dentro de cada hospital las resenas se
etiquetan por rotacion + semestre + periodo + n participantes.

NO hay calificaciones numericas en la fuente. No se inventan estrellas: la tarjeta lidera
con el texto cualitativo (positivos / por mejorar / problemas) y un conteo de resenas.

MODERACION: el texto es fiel a los reportes PERO sin nombres reales de docentes. Toda
mencion nominal (Dr./Dra. <nombre>) se reemplaza por el rol ("un docente", "los
especialistas", "el neonatologo", "el coordinador"...). Las denuncias graves de conducta
hacia pacientes o estudiantes ademas se resumen por el problema, sin reproducir la
acusacion textual. Es un sitio publico: ningun individuo queda senalado por su nombre.

Algunas sedes mencionadas en las resenas no estan en el plan ME03 (San Blas, Roosevelt,
Eusalud, Virrey Solis): se incluyen con su 'name' propio; la UI las muestra aunque no
esten en hospitals.json.
"""
import os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "model", "hospital_reviews.json")

SOURCE = "Conectados Rotando · Trimestrales 2026-1 (Representación estudiantil de Medicina)"

# Display names for sites NOT in the ME03-plan-derived hospitals.json
EXTRA_NAMES = {
    "san-blas":     "Hospital de San Blas",
    "roosevelt":    "Instituto de Ortopedia Infantil Roosevelt",
    "eusalud":      "Eusalud",
    "virrey-solis": "Virrey Solís IPS",
}

# rev(rotation, semester, n, positivos, por_mejorar, problemas, quotes=None)
def rev(rotation, sem, n, pos="", mej="", prob="", quotes=None):
    r = {"rotation": rotation, "semester": sem, "period": "2026-1", "n": n}
    if pos:  r["positivos"] = pos
    if mej:  r["por_mejorar"] = mej
    if prob: r["problemas"] = prob
    if quotes: r["quotes"] = quotes
    return r

REVIEWS = {
 "hu-mayor": [
   rev("Bloque Clínico I · Medicina Interna", "VII", 22,
       "Se destaca la calidad académica del bloque: los quizzes semanales para reforzar el "
       "estudio continuo, las revisiones de tema de varios docentes y clases magistrales "
       "completas y bien estructuradas. Los docentes son comprometidos y fomentan el razonamiento "
       "clínico. La dinámica del 'caso clínico difícil' y la electiva de cuidado primario "
       "reciben muy buenos comentarios. Horarios adecuados y buena variedad de pacientes.",
       "Optimizar la planeación de turnos, que hoy se cruzan con electivas y otras "
       "rotaciones; gestionar esos conflictos debería recaer en la coordinación y no en el "
       "estudiante. Mayor homogeneidad en las revisiones de tema y posibilidad de rotar "
       "entre varios docentes. Limitada disponibilidad de computadores para notas y "
       "sobrecarga de estudiantes en algunos servicios. Ajustar entrega de bonos y tiempos "
       "de los quices.",
       "Se reportan experiencias negativas con un docente por lenguaje inapropiado y "
       "desmotivante. También bajo compromiso de algunos docentes (ausencia de revisiones "
       "o presentaciones) y falta de acompañamiento en turnos, con ausencias prolongadas "
       "sin aviso."),
   rev("Bloque Clínico II · Cirugía General", "VII", 22,
       "Alta calidad docente, con especialistas y residentes comprometidos. Rotación muy "
       "práctica: se participa en procedimientos, salas de cirugía y urgencias. Diversidad "
       "de escenarios (cirugía general, ortopedia, anestesia) y un ambiente humano "
       "respetuoso y motivador.",
       "En algunos servicios (urgencias) la carga horaria no corresponde con las "
       "actividades y hay tiempos muertos. Se pide mayor claridad en la planificación del "
       "bloque y en la estructura de contenidos.",
       "Casos puntuales de comunicación inapropiada y trato descalificante de ciertos "
       "docentes, sobre todo en salas de cirugía. Cambios de último momento en actividades "
       "evaluativas. En la consulta externa de Virrey Solís se reportan experiencias "
       "negativas de trato."),
   rev("Bloque Clínico III · Neonatología", "VIII", 26,
       "Dejan adaptar a los bebés; tanto los médicos de salas como la doctora de consulta "
       "externa explican las cosas y buscan que el estudiante aprenda.",
       "En UCI algunos médicos son poco receptivos y buena parte del tiempo no se hace "
       "mucho, en parte porque los residentes, también ocupados, no alcanzan a acompañar."),
   rev("Bloque Clínico III · Ginecología y Obstetricia", "VIII", 26, "",
       "Los turnos de 12 horas se perciben como excesivos. La carga asistencial es alta y "
       "limita el tiempo de estudio; hay poca claridad sobre lo que se espera del "
       "estudiante dentro del servicio."),
   rev("Bloque Clínico IV · Neurología", "VIII", 26,
       "Buena exposición clínica y alta demanda asistencial, que permite observar "
       "múltiples patologías neurológicas complejas y fortalece el razonamiento clínico.",
       "Fue la sede con más críticas en neurología. El horario se describe como muy "
       "agotador, con jornadas de 6 a.m. a 8 p.m. Se reporta demasiado tiempo muerto y que "
       "casi no se deja presentar pacientes ni hacer notas.",
       "", ["Sumamente agotador e inhumano.",
            "Uno se queda esperando sin hacer nada."]),
   rev("Bloque Clínico IV · Oftalmología", "VIII", 26,
       "Para varios es muy buena rotación: los doctores explican, hay un taller de "
       "anatomía dinámico y la residente está siempre dispuesta a enseñar y a correlacionar "
       "los temas con los casos.",
       "Experiencias muy dispares. En el turno de la tarde (1:30 a 7:00 p.m.) varios "
       "refieren que casi no se hace nada salvo oftalmoscopias esporádicas, sin docencia "
       "ni revisiones. Se pide dejar participar más a los estudiantes y compartir el "
       "material de clase. Se reportan además trato grosero y comentarios irrespetuosos de "
       "un docente, junto con incumplimiento de horarios."),
   rev("Bloque Clínico IV · Otorrinolaringología", "VIII", 26,
       "Rotación considerada excelente por las revisiones de tema frecuentes y la calidad "
       "del ambiente académico. Buena organización, docentes dispuestos a enseñar y "
       "horario adecuado, con buen equilibrio entre exigencia y bienestar.",
       "Varias veces no se permite practicar acompañado de un médico, por lo que parte del "
       "tiempo no se hace nada. Un docente fue descrito como conflictivo con algunos "
       "pacientes y sin dar retroalimentación."),
   rev("MSP 1 · Especialidades clínico-quirúrgicas", "IX", 20, "",
       "En cirugía general hay demasiados estudiantes rotando por el servicio y la "
       "posibilidad de participar es casi nula. En cirugía hepatobiliar se deja de lado lo "
       "académico por lo asistencial y los horarios son excesivos (de domingo a domingo, "
       "desde las 5 a.m.). En cirugía vascular las responsabilidades son escasas (una o "
       "dos interconsultas al día). En dolor y cuidado paliativo se pierde tiempo en la "
       "mañana esperando la asignación de pacientes."),
 ],

 "cardioinfantil": [
   rev("Bloque Clínico I · Medicina Interna", "VII", 22,
       "Alta calidad académica, con enfoque pedagógico y compromiso de los docentes. "
       "Ambiente estructurado y exigente que favorece un aprendizaje significativo y el "
       "razonamiento clínico. Acompañamiento constante, disposición para resolver dudas y "
       "un genuino interés en la formación integral. Ambiente respetuoso, sin conductas "
       "inapropiadas, y horarios adecuados y respetados.",
       "Las evaluaciones MRC y PSM deberían ser más equitativas: los estudiantes de HUM "
       "tienen ventaja porque sus quizzes semanales comparten preguntas con esos exámenes, "
       "lo que genera notas dispares entre sitios y pesa en procesos futuros como "
       "residencias. Hay cambios imprevistos de salón, retrasos y clases fundamentales que "
       "no se dictan en fecha ni se reponen (insuficiencia respiratoria, diabetes, HTA).",
       "La mayoría no reporta inconvenientes significativos; destacan una buena "
       "experiencia y un ambiente muy académico."),
   rev("Bloque Clínico II · Cirugía General", "VII", 22,
       "Se destaca la organización del bloque por parte del coordinador, su profesionalismo y "
       "dedicación para que el aprendizaje sea significativo, práctico y clínico. Los "
       "especialistas integran activamente a los estudiantes en dinámicas hospitalarias y "
       "quirúrgicas, con interacción con pacientes y participación en procedimientos.",
       "En pisos y urgencias la participación es limitada y predominan actividades no "
       "formativas. Se pide fortalecer habilidades quirúrgicas básicas (sutura, sonda "
       "vesical, manejo del entorno quirúrgico). La evaluación debería valorar también "
       "asistencia, compromiso y participación, no solo el examen.",
       "En pisos y urgencias algunos residentes generan mal ambiente por el estrés y la "
       "carga, y en ocasiones asignan a los estudiantes tareas personales o "
       "extrainstitucionales."),
   rev("Bloque Clínico IV · Neurología", "VIII", 26,
       "Buen acompañamiento de algunos residentes y posibilidad de participar más "
       "activamente en la valoración clínica. Buena enseñanza práctica y una integración "
       "al servicio que favorece el desarrollo de habilidades diagnósticas."),
   rev("Bloque Clínico IV · Otorrinolaringología", "VIII", 26,
       "Los doctores son muy académicos, con gran disposición para enseñar y revisiones de "
       "tema diarias que fortalecen el aprendizaje. Rotación muy enriquecedora: la "
       "exigencia constante obliga a estudiar de forma activa y todos los doctores y "
       "residentes tienen excelente actitud."),
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Buen sitio de rotación, con doctores dispuestos a enseñar y un ambiente agradable "
       "con todo el personal del servicio.",
       "", "", ["Buen sitio de rotación y doctores dispuestos a enseñar, un ambiente "
                "agradable y no incómodo con todas las personas del servicio."]),
 ],

 "centenario": [
   rev("Bloque Clínico I · Medicina Interna", "VII", 22,
       "Acompañamiento docente cercano y personalizado. Se asigna un hospitalario por "
       "estudiante, lo que facilita resolver dudas, hacer revisiones de tema y un "
       "seguimiento continuo. Internistas y especialistas con actitud docente activa. Buen "
       "volumen y diversidad de pacientes, con participación real en la valoración y el "
       "seguimiento integral, incluyendo estudios diagnósticos.",
       "Las clases y revisiones de tema no tienen cronograma fijo y a veces se anuncian el "
       "mismo día. La evaluación no siempre recoge la retroalimentación de los "
       "especialistas con quienes más se rota. En las electivas no hay claridad inicial "
       "sobre qué servicios estarán disponibles y se ofrecen algunos que no funcionan. "
       "Faltan espacios de bienestar y de alimentación: no hay cafetería ni un lugar para "
       "descansar, y a veces las jornadas se extienden más allá de las 5:00 p.m.",
       "La mayoría no reporta inconvenientes graves. Se menciona la limitada "
       "disponibilidad de computadores, que dificulta revisar paraclínicos y elaborar "
       "evoluciones, y la falta de espacios para el estudiante."),
   rev("Bloque Clínico II · Cirugía General", "VII", 22,
       "Entorno cercano y muy participativo por el bajo número de estudiantes, lo que "
       "permite interacción directa con los especialistas. Buena disposición docente de "
       "los hospitalarios y de los especialistas. Anestesiología y urgencias (en San "
       "Rafael) destacan por su organización académica.",
       "En cirugía general y ortopedia el volumen de pacientes o de insumos limita la "
       "práctica, lo que afecta rotaciones cortas como ortopedia. Se pide una figura de "
       "coordinación académica más definida y un cronograma claro. Algunos contenidos "
       "teóricos resultan demasiado extensos para el tiempo asignado.",
       "La mayoría no reporta inconvenientes. Se señala el bajo volumen de pacientes en "
       "cirugía, sobre todo en ortopedia, y que la falta de servicio de urgencias en la "
       "institución limita la exposición a patología aguda."),
 ],

 "san-rafael": [
   rev("Bloque Clínico I · Medicina Interna", "VII", 22,
       "Entorno muy favorable para el aprendizaje, con enfoque académico sólido. Los "
       "docentes tienen gran disposición para enseñar y promueven revisiones de tema, "
       "exposiciones y revistas dinámicas e interactivas. Horarios adecuados.",
       "Debería socializarse mejor con los especialistas el horario y el rol del "
       "estudiante dentro de los servicios, para fomentar su participación en las "
       "actividades clínicas.",
       "Se reportan inconvenientes administrativos: ausencia de inducción oportuna, falta "
       "de asignación de lockers, y la percepción de que las tutorías parecen exclusivas "
       "de HUM y la FCI, sin acompañamiento para los demás hospitales."),
   rev("Bloque Clínico II · Cirugía General", "VII", 22, "", "",
       "El estudiante aún no había finalizado su rotación por los servicios, por lo que no "
       "reporta aspectos concluyentes. Hasta el momento, sin problemas significativos."),
   rev("Bloque Clínico IV · Neurología", "VIII", 26, "",
       "Sede abierta este semestre para ampliar cupos, pero con poca actividad: no había "
       "neurólogo de base, la jornada terminaba al mediodía y en la práctica solo se "
       "rotaba martes y jueves. No había revisión de temas ni discusión de casos, por lo "
       "que la experiencia resultó muy limitada."),
 ],

 "bosa": [
   rev("Bloque Clínico I · Medicina Interna", "VII", 22,
       "Buen acompañamiento de los médicos del hospital, lo que favorece el aprendizaje y "
       "la integración del estudiante en el equipo asistencial.",
       "Debería existir más acompañamiento y coordinación por parte de la universidad, "
       "sobre todo en la organización de clases y la definición clara de horarios.",
       "Sin problemas reportados hasta el momento."),
   rev("Bloque Clínico II · Cirugía General", "VII", 22,
       "Se resaltan los servicios de cirugía general y ortopedia, con un buen proceso de "
       "aprendizaje y oportunidades de aplicación práctica.",
       "Dificultades importantes en anestesiología: ausencia de acompañamiento docente, "
       "falta de indicaciones claras de horarios y actividades, y escasa orientación. "
       "Algunos estudiantes no recomiendan ese servicio y sugieren reasignarlo a otra "
       "institución.",
       "Un estudiante perdió la rotación de anestesiología tras una serie de fallas de "
       "acompañamiento institucional y docente (sin inducción, sin comunicación oportuna "
       "de horarios y criterios de evaluación, y manejo deficiente de una incapacidad "
       "médica), situación que escaló a gestión académica."),
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Excelente rotación: se hace de todo (hospitalización, urgencias, partos y "
       "cesáreas) y al estudiante de pediatría lo dejan adaptar al recién nacido. Uno de "
       "los pediatras enseña de forma muy completa y con carisma. Hay parqueadero gratis.",
       "Quedan lejos y no hay casilleros para guardar las cosas, con riesgo de pérdidas; "
       "según gestión, por falta de convenio. Cuando hay tarde académica en la "
       "universidad es difícil llegar a tiempo.",
       "", ["Es una excelente rotación, se hacen demasiadas cosas. A uno como estudiante "
            "de pediatría lo dejan adaptar, cosa que en muchos puntos no se puede hacer."]),
 ],

 "kennedy": [
   rev("Bloque Clínico III · Neonatología", "VIII", 26,
       "El sitio cuenta con módulos por los que pasa el estudiante (adaptación neonatal, "
       "lactancia materna, UCI neonatal), propicios para temas clave del médico general. "
       "Dejan involucrarse activamente en los procedimientos y hacen revisiones académicas "
       "oportunas.",
       "Se reporta un ambiente difícil en el servicio: trato hostil hacia los estudiantes, "
       "revisiones asignadas de un día para otro y temas de parcial que no se vieron. Se "
       "describe un clima que desmotiva y que dificulta preguntar."),
   rev("Bloque Clínico III · Ginecología y Obstetricia", "VIII", 26, "",
       "No se hizo inducción y la coordinación no se comunicó con el grupo. Algunos "
       "servicios no requieren estudiantes todo el tiempo, lo que deja horas perdidas, y "
       "en consulta externa de la mañana casi no se ve paciente.",
       "Se reportó un episodio grave de trato gravemente irrespetuoso e inapropiado hacia "
       "una paciente que cursaba una pérdida gestacional, además de intentos de "
       "responsabilizar a los estudiantes. El caso quedó consignado en el reporte de la "
       "representación estudiantil."),
   rev("Bloque Clínico IV · Neurología", "VIII", 26,
       "La alta carga asistencial da gran exposición a patología neurológica frecuente, lo "
       "que fortalece el aprendizaje clínico y el razonamiento diagnóstico. Ver múltiples "
       "pacientes facilita comprender la neurología aplicada.",
       "Se reportan tiempos prolongados de espera entre actividades clínicas, con "
       "momentos de menor aprovechamiento académico."),
   rev("MSP 1 · Cirugía plástica", "IX", 20, "",
       "Servicio al que le falta orden: cuentan con un solo cirujano que a veces llega a "
       "mediodía, sin hora de salida garantizada, y se tiene más acercamiento con el "
       "hospitalario que con el especialista. Se reportan comentarios inapropiados del "
       "doctor."),
 ],

 "samaritana": [
   rev("Bloque Clínico III · Neonatología", "VIII", 26,
       "El neonatólogo es un excelente docente, con enfoque académico y revisiones "
       "constantes sobre temas pertinentes. La rotación está bien estructurada y permite "
       "una alta participación.",
       "", "", ["El neonatólogo es un excelente docente con un enfoque académico para la "
                "rotación, con revisiones constantes sobre temas pertinentes."]),
   rev("MSP 1 · UCI", "IX", 20, "",
       "Se sugiere un carné provisional que permita la entrada por el acceso de personal y "
       "evite hacer la fila de pacientes."),
 ],

 "paz": [
   rev("Bloque Clínico IV · Psiquiatría II", "VIII", 26,
       "Percepción general positiva por la buena pedagogía de algunos docentes y el "
       "aprendizaje en consulta externa. Trato respetuoso y buena orientación clínica, con "
       "espacio para fortalecer la entrevista psiquiátrica y el razonamiento diagnóstico.",
       "Se sugiere mejorar la estructura de algunas actividades complementarias, como el "
       "cineforo, con mayor discusión clínica y análisis de casos reales."),
   rev("Bloque Clínico IV · Psiquiatría I", "VIII", 26,
       "Los estudiantes destacan el respeto de los docentes, la buena inducción "
       "institucional y la oportunidad de interactuar de forma cercana con pacientes "
       "psiquiátricos, enriquecedor para la formación clínica y humana.",
       "Faltan más revisiones de tema y el cineforo termina siendo solo llenar un "
       "formulario; se pide fortalecer el componente académico y la discusión grupal."),
 ],

 "inmaculada": [
   rev("Bloque Clínico IV · Psiquiatría II", "VIII", 26,
       "Algunos estudiantes resaltan la oportunidad de participar en consulta externa y en "
       "el abordaje de pacientes psiquiátricos, lo que fortalece la entrevista clínica y "
       "la integración de la teoría con la práctica.",
       "Fue la sede con mayores dificultades organizativas: no se sabía qué doctor estaba "
       "asignado, se perdía tiempo sin saber a dónde ir y no se cumplían bien los "
       "horarios, con pérdida de actividades prácticas."),
 ],

 "cisne": [
   rev("Bloque Clínico IV · Psiquiatría II", "VIII", 26,
       "En Campo Nuevo se destaca la calidad del aprendizaje: al haber menor volumen de "
       "pacientes, se facilita una valoración más detallada de cada caso y se profundiza "
       "en la semiología psiquiátrica y el abordaje integral.",
       "El tiempo compartido con el especialista es poco."),
 ],

 "country": [
   rev("Bloque Clínico IV · Otorrinolaringología", "VIII", 26,
       "Descrita como una de las mejores experiencias de la rotación. Se destaca la labor "
       "de los especialistas por su dedicación, sus ganas de enseñar y un "
       "trato respetuoso y cercano. Buen horario y adecuado equilibrio entre exigencia y "
       "bienestar.",
       "", "", ["Una excelente rotación."]),
 ],

 "colsanitas": [
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Todo muy organizado y los doctores muy atentos.",
       "", "", ["Todo muy organizado y los doctores muy atentos."]),
   rev("Bloque Clínico IV · Otorrinolaringología", "VIII", 26,
       "Se resalta el respeto por el horario académico (se sale al mediodía) y las "
       "revisiones de tema dos veces por semana, que refuerzan conocimientos de forma "
       "dinámica.",
       "La participación práctica es muy limitada: básicamente toma de signos vitales y, "
       "en pacientes específicos, una otoscopia. Poca interacción y poca profundización en "
       "temas esenciales; varios describen el tiempo diario como largo y desaprovechado."),
 ],

 "tintal": [
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Los doctores son muy amables e interesados en el aprendizaje de los estudiantes.",
       "No hay una inducción clara, por lo que el primer día uno está muy perdido.",
       "", ["Los doctores son muy amables e interesados por el aprendizaje de los "
            "estudiantes."]),
 ],

 "cardiovascular-nino": [
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Se aprende mucho en la rotación.",
       "Un docente no siempre tiene la mejor forma de comunicarse y no suele estar abierto "
       "a otros puntos de vista, lo que dificulta el diálogo académico. Se reporta además "
       "el trato hostil y humillante de otro docente durante revistas y revisiones de "
       "tema."),
 ],

 "infantil-colsubsidio": [
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Ambiente muy académico donde se aprende mucho.",
       "", "", ["Ambiente muy académico donde se aprende mucho."]),
 ],

 "meissen": [
   rev("Bloque Clínico III · Neonatología", "VIII", 26,
       "Sede incluida entre los lugares de rotación de neonatología del bloque."),
 ],

 "oftalmologica": [
   rev("Bloque Clínico IV · Oftalmología", "VIII", 26,
       "En Fundonal los especialistas hacen revisiones y talleres muy informativos. A "
       "pesar de estar en consulta hay muchas oportunidades de participar y aprender de "
       "los pacientes, e incluso de ingresar a las cirugías del servicio.",
       "La revisión a cargo de residentes debería pasar a los especialistas: en un grupo "
       "la residente no ofreció lineamientos claros, horario ni retroalimentación "
       "constructiva, lo que restó oportunidad de aprender un tema importante con un "
       "experto."),
 ],

 # --- sites not in the ME03 plan (carry their own display name) ---
 "san-blas": [
   rev("Bloque Clínico III · Pediatría", "VIII", 26, "",
       "No se aprende mucho en la rotación."),
 ],
 "eusalud": [
   rev("Bloque Clínico III · Neonatología", "VIII", 26,
       "Se destacan las revisiones de tema con el neonatólogo y que todos los doctores "
       "fueron muy respetuosos."),
   rev("Bloque Clínico III · Ginecología y Obstetricia", "VIII", 26, "",
       "Se menciona en repetidas ocasiones la mala actitud de las hospitalarias."),
 ],
 "virrey-solis": [
   rev("Bloque Clínico II · Cirugía General · Consulta externa", "VII", 22, "",
       "Se reportan experiencias negativas relacionadas con el trato hacia los estudiantes "
       "en la consulta externa."),
 ],
 "roosevelt": [
   rev("Bloque Clínico III · Pediatría", "VIII", 26,
       "Sede incluida entre los lugares de rotación de pediatría del bloque."),
 ],
}

# Guard: no real doctor names may reach the public site. A nominal mention is an honorific
# (Dr./Dra./Doctor/Doctora) followed by a capitalized word. Roles ("un docente", "el
# neonatologo") are fine; this only fires on Honorific + Name.
_NAME_RE = re.compile(r"(?:Dr\.?|Dra\.?|Doctor|Doctora)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+")

def _assert_no_names(out):
    hits = []
    for hid, h in out["hospitals"].items():
        for r in h["reviews"]:
            blob = " ".join([r.get("positivos", ""), r.get("por_mejorar", ""),
                             r.get("problemas", "")] + r.get("quotes", []))
            hits += [(hid, m) for m in _NAME_RE.findall(blob)]
    if hits:
        raise SystemExit(f"ABORT: real doctor names found (no nombres reales): {hits}")

def main():
    out = {"source": SOURCE, "extra_names": EXTRA_NAMES, "hospitals": {}}
    total = 0
    for hid, revs in REVIEWS.items():
        out["hospitals"][hid] = {"reviews": revs}
        if hid in EXTRA_NAMES:
            out["hospitals"][hid]["name"] = EXTRA_NAMES[hid]
        total += len(revs)
    _assert_no_names(out)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(REVIEWS)} hospitals con reseñas, {total} reseñas -> {OUT}")
    for hid, revs in sorted(REVIEWS.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(revs):2} · {hid}")

if __name__ == "__main__":
    main()
