"""CLI para Dxrk Enterprise."""

import sys


def enterprise_cli(args):
    if not args:
        print_usage()
        return
    command = args[0]
    if command == "start":
        from .company import DxrkEnterprise

        company = DxrkEnterprise()
        company.start_company()
        print("Dxrk Enterprise started!")
        print(company.generate_company_report())
    elif command == "stop":
        from .company import DxrkEnterprise

        company = DxrkEnterprise()
        company.stop_company()
        print("Dxrk Enterprise stopped.")
    elif command == "status":
        from .company import DxrkEnterprise

        company = DxrkEnterprise()
        print(company.generate_company_report())
    elif command == "execute":
        if len(args) < 2:
            print("Usage: dxrk-py enterprise execute <task> [department]")
            return
        from .company import DxrkEnterprise

        company = DxrkEnterprise()
        company.start_company()
        task = args[1]
        dept = args[2] if len(args) > 2 else None
        result = company.execute_task(task, dept)
        print(f"Result: {result}")
    elif command == "skills":
        from .company import DxrkEnterprise

        company = DxrkEnterprise()
        for dept_id, skills in company.list_all_skills().items():
            print(f"\n{dept_id.upper()}:")
            for skill in skills:
                status = "yes" if skill["installed"] else "no"
                print(f"  [{status}] {skill['name']}")
    elif command == "report":
        from .company import DxrkEnterprise

        company = DxrkEnterprise()
        print(company.generate_company_report())
    else:
        print(f"Unknown command: {command}")
        print_usage()


def print_usage():
    print("""
DXRK ENTERPRISE CLI
  dxrk-py enterprise start          - Iniciar empresa
  dxrk-py enterprise stop           - Detener empresa
  dxrk-py enterprise status         - Ver estado
  dxrk-py enterprise execute <task> - Ejecutar tarea
  dxrk-py enterprise skills         - Listar skills
  dxrk-py enterprise report         - Generar reporte
""")


if __name__ == "__main__":
    enterprise_cli(sys.argv[1:])
