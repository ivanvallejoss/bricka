# Sentinel para distinguir "no enviado" de None en updates parciales.
# Usar cuando None es un valor de negocio válido que no debe confundirse
# con "el caller no envió este campo".
#
# Ejemplo canónico — update_deal:
#   agent_id=None  → desasignar agente explícitamente
#   agent_id=UNSET → campo no enviado, no modificar
UNSET = object()