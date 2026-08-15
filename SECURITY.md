# Política de seguridad

Tómate en serio la seguridad de Dxrk. Reportar vulnerabilidades de forma responsable ayuda a mantener el ecosistema seguro para todos.

## Versiones soportadas

| Versión | Soportada |
| ------- | --------- |
| 0.1.x   | ✅ Sí     |
| < 0.1   | ❌ No     |

## Reportar una vulnerabilidad

**NO abras un issue público para vulnerabilidades de seguridad.** Usa uno de estos canales privados:

1. **Security Advisories de GitHub** (preferido): ve a [github.com/Dxrk777/Dxrk/security/advisories/new](https://github.com/Dxrk777/Dxrk/security/advisories/new) y crea un advisory privado.
2. **Discusión privada**: abre una discusión en GitHub Discussions marcada como solo para mantenedores.

### Qué incluir en el reporte

- Descripción de la vulnerabilidad y su impacto potencial.
- Pasos reproducibles (código, comandos, versión afectada).
- Mitigaciones sugeridas si las conoces.

### Qué esperar

- Confirmación de recepción en un plazo de 48 horas.
- Evaluación de severidad e impacto.
- Cronograma de corrección y release con el fix.
- Crédito público al reporter si así lo deseas.

## Buenas prácticas de seguridad del proyecto

- Nunca se commiten secretos (tokens, API keys, contraseñas). El repo tiene .gitignore que cubre `.env` y `dist/`.
- Los tokens de PyPI/API viven SOLO en archivos locales fuera del repo (`.pypirc`, `.env`, variables de entorno).
- Los cambios con impacto en seguridad pasan revisión de código y el CI ejecuta mypy + pytest en cada PR.
