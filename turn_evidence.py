"""Evidencia del ejecutor dentro del turno compartido."""
import json
import re

from local_files import RESULT_HEADER
from process_tools import PROCESS_NAMES, TERMINAL, latest_runs
from tasks import complete_page_versions


READ_SOURCES = {"inspect_local_files": "archivos locales", "rank_local_files": "archivos locales",
                "read_project_file": "archivo del proyecto"}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def structured(content):
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


class Evidence:
    def __init__(self):
        self.observations = []
        self.pages = {}
        self.file_versions = {}

    def file_page(self, data, revision):
        file, offset = data["archivo"], data["inicio"]
        self.file_versions[file] = revision
        self.pages[file, offset, revision] = {"arguments": {"offset": offset},
                                            "next_offset": data["desplazamiento_siguiente"],
                                            "partial": not data["fin_de_archivo"]}

    def record(self, name, arguments, result, step):
        data = {}
        if name in PROCESS_NAMES or name in READ_SOURCES:
            data = structured(result.content)
        if name in PROCESS_NAMES:
            fields = {"procedencia": "supervisor de Windows", "estado": data.get("estado", result.status),
                      "codigo": data.get("codigo")}
            if result.code == "OPERACION_DENEGADA":
                fields["efecto"] = "denegado"
            for key in ("id", "inicio_confirmado", "cursor", "hay_mas", "truncada", "cancelacion_solicitada"):
                if key in data:
                    fields[key] = data[key]
            if data.get("id"):
                fields["cobertura"] = "parcial" if data.get("parcial") else "completa"
                if data.get("parcial"):
                    fields["cursor_siguiente"] = data["cursor"] if data.get("hay_mas") or fields["estado"] not in TERMINAL else None
        elif name in READ_SOURCES:
            fields = {"procedencia": READ_SOURCES[name], "estado": data.get("estado", "error")}
            for key in ("cobertura", "truncado", "recursivo", "total", "coincidencias_observadas", "omitidas"):
                if key in data:
                    fields[key] = data[key]
            if name == "read_project_file" and fields["estado"] == "ok":
                fields["cobertura"] = ("completa" if (data["archivo"], self.file_versions.get(data["archivo"]))
                                        in complete_page_versions(self.pages) else "parcial")
                if result.model_content:
                    fields["directivas_aisladas"] = structured(result.model_content)["directivas_aisladas"]
            if "cursor_siguiente" in data or "desplazamiento_siguiente" in data:
                fields["cursor_siguiente"] = data.get("cursor_siguiente", data.get("desplazamiento_siguiente"))
        elif result.evidence:
            fields = result.evidence
            if fields["procedencia"] == "MCP" and fields.get("cobertura") == "parcial":
                data = {"extracto": result.content[:2000]}
        else:
            return None
        fields = {**fields, "observacion": len(self.observations) + 1}
        self.observations.append((name, fields, data))
        return fields

    def process_output(self, process, run_id):
        pages = {(data.get("cursor_inicio", 0), data["cursor"]): data["salida"] for item, data in process
                 if item.get("id") == run_id and data.get("salida")}
        # Una relectura puede incluir páginas ya observadas. Preferir el rango mayor ante un mismo inicio.
        delivered = []
        previous_end = -1
        for start, end in sorted(pages, key=lambda bounds: (bounds[0], -bounds[1])):
            if start >= previous_end:
                if delivered and start != previous_end:
                    delivered.append("\n[Intervalo de salida sin observar]\n")
                delivered.append(pages[start, end])
                previous_end = end
        return CONTROL_CHARS.sub("", "".join(delivered)).strip("\r\n")

    def limitations(self):
        latest = {}
        complete_files = complete_page_versions(self.pages)
        for name, fields, data in self.observations:
            source = fields["procedencia"]
            if name in PROCESS_NAMES:
                continue
            if source == "archivo del proyecto" and data.get("archivo"):
                file = data["archivo"]
                latest[source, file] = (fields, (file, self.file_versions.get(file)) not in complete_files)
            elif source == "MCP":
                # Una página final no acredita las otras páginas del conector.
                latest[source, fields["observacion"]] = (fields, fields.get("cobertura") == "parcial")
            else:
                latest[source, fields["observacion"]] = (fields, fields.get("cobertura") == "parcial" or
                                                          fields.get("truncado") is True)
        return [(fields, partial) for fields, partial in latest.values() if partial or fields.get("efecto") in
                {"sin confirmación independiente", "sin confirmar", "denegado"}]

    def partial(self):
        latest = {fields["id"]: fields for name, fields, _ in self.observations if name in PROCESS_NAMES and "id" in fields}
        return any(partial for _, partial in self.limitations()) or any(
            fields.get("cobertura") == "parcial" for fields in latest.values())

    def process_only(self):
        return bool(self.observations) and all(name in PROCESS_NAMES for name, _, _ in self.observations)

    def partial_mcp_only(self):
        return bool(self.observations) and all(
            fields["procedencia"] == "MCP" and fields.get("cobertura") == "parcial" and not fields.get("efecto")
            for _, fields, _ in self.observations)

    def answer(self, text, steps, *, stopped, preserve):
        process = [(fields, data) for name, fields, data in self.observations if name in PROCESS_NAMES]
        latest = {fields["id"]: fields for fields, _ in process if "id" in fields}
        reports = []
        for run_id, fields in latest.items():
            state = fields["estado"]
            code = fields["codigo"]
            line = f"Estado del proceso: **{state}** · Código de terminación: **{code if code is not None else 'sin registrar'}**"
            line += f" · ID `{run_id}`."
            if fields.get("cancelacion_solicitada") and state not in TERMINAL:
                line += " Cancelación solicitada."
            if state == "preparando":
                line += " Inicio aún sin confirmar."
            if fields.get("truncada"):
                line += " El supervisor alcanzó el límite de salida retenida."
            if fields.get("cursor_siguiente") is not None:
                line += f" Cursor para continuar: {fields['cursor_siguiente']}."
            output = self.process_output(process, run_id)
            if output:
                line += "\n\nSalida observada\n\n" + "\n".join("    " + row for row in output[:3000].splitlines())
                if len(output) > 3000:
                    line += "\n\nVista abreviada a 3000 caracteres. Consulta el ID para releer la salida retenida."
            reports.append(line)
        for run_id, (state, cancel) in latest_runs(steps).items():
            if run_id not in latest and state not in TERMINAL:
                reports.append(f"Estado registrado del proceso: **{state}** · ID `{run_id}`."
                               + (" Cancelación solicitada." if cancel else ""))
        for fields, data in process:
            if data.get("ejecuciones_recientes") is not None and not latest:
                ids = ", ".join(f"`{run_id}`" for run_id in data["ejecuciones_recientes"])
                reports.append(f"Ejecuciones registradas en este chat: {ids or 'ninguna'}.")
            elif fields["estado"] == "sin ejecutar" and not data:
                reports.append("La operación de proceso fue denegada." if fields.get("efecto") == "denegado"
                               else "La operación de proceso quedó sin ejecutar.")
        if reports and self.process_only() and not (stopped or preserve):
            return "\n\n".join(dict.fromkeys(reports))
        for fields, partial in self.limitations()[-5:]:
            line = f"Observación {fields['observacion']} · {fields['procedencia']}"
            if partial:
                line += " · datos parciales"
                if fields.get("truncado"):
                    line += " · resultado truncado"
                if fields.get("cursor_siguiente") is not None:
                    line += " · hay una continuación indicada por la herramienta"
                if fields.get("continuacion") == "cursor repetido":
                    line += " · cursor repetido; el recorrido quedó sin verificar"
            if fields.get("efecto"):
                line += f" · efecto {fields['efecto']}"
            reports.append(line + ".")
        if not stopped and self.partial_mcp_only():
            reports.append("La cobertura del conjunto y su total quedan sin verificar.")
            excerpts = dict.fromkeys(data["extracto"] for _, _, data in self.observations if data.get("extracto"))
            for excerpt in list(excerpts)[-3:]:
                reports.append("Extracto recibido\n\n" + "\n".join(
                    "    " + row for row in CONTROL_CHARS.sub("", excerpt).splitlines()))
            if not preserve:
                return "\n\n".join(dict.fromkeys(reports))
        if reports:
            return "\n\n".join([*dict.fromkeys(reports), text.removeprefix(RESULT_HEADER)]).strip()
        return text
