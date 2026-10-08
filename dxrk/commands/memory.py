# SPDX-License-Identifier: MIT
"""Memory command"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dxrk.security.enforcement import require_op, resolve_user

from .registry import Command, CommandContext, Flag, Registry


def _meminfo() -> tuple[int, int]:
    """Returns (total_kb, available_kb) from /proc/meminfo."""
    total = 0
    available = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
                if total and available:
                    break
    except OSError:
        pass
    return total, available


def _process_rss_kb() -> int:
    try:
        with open(f"/proc/{os.getpid()}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    if sys.platform == "win32":
        return 0
    import resource

    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ValueError, OSError):
        return 0


def register_memory_command(reg: Registry) -> None:
    """Registers the `dxrk memory` command and its subcommands."""

    def run(ctx: CommandContext) -> int:
        try:
            require_op(ctx.tenant_id, resolve_user(), "read")
        except PermissionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        out = ctx.out
        total_kb, available_kb = _meminfo()
        rss_kb = _process_rss_kb()

        out.write("Uso de memoria\n")
        out.write("──────────────\n")
        if total_kb:
            used_kb = total_kb - available_kb
            out.write(f"  Sistema:  {used_kb / 1024:.0f} MB en uso de {total_kb / 1024:.0f} MB\n")
        else:
            out.write("  Sistema:  desconocido\n")
        out.write(f"  Proceso: {rss_kb / 1024:.1f} MB (RSS)\n")
        return 0

    cmd = Command(
        name="memory",
        short="Mostrar el uso de memoria",
        run=run,
    )
    reg.add_command(cmd)

    # Fase 2: Eval Harness
    def eval_run_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            import os

            from dxrk.memory.eval_harness import EvalHarness, generate_synthetic_queries
            from dxrk.memory.palace import DxrkMemory

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                harness = EvalHarness(dm, Path(palace_path) / "eval")
                n_q = int(ctx.flags.get("n", "10"))
                queries = generate_synthetic_queries(dm, wing=ctx.args[0] if ctx.args else "default", n=n_q)
                report = harness.run(wing=ctx.args[0] if ctx.args else "default", queries=queries)
                out = ctx.out
                out.write(f"Evaluación: {report.wing}\n")
                out.write(f"  Queries: {report.num_queries}\n")
                out.write(f"  Recall@k: {report.recall_at_k}\n")
                out.write(f"  MRR: {report.mrr:.3f}\n")
                out.write(f"  NDCG: {report.ndcg:.3f}\n")
                out.write(f"  ECE: {report.ece:.3f}\n")
                out.write(
                    f"  Latencia p50/p95/p99: {report.latency_p50:.1f}/{report.latency_p95:.1f}/{report.latency_p99:.1f}ms\n"
                )
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory eval run",
            short="Ejecutar evaluación harness en un wing",
            flags={"n": Flag("n", shorthand="n", default="10", help="Número de queries")},
            min_args=1,
            max_args=1,
            run=run,
        )
        return cmd

    def eval_synthetic_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.eval_harness import generate_synthetic_queries
            from dxrk.memory.palace import DxrkMemory

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                queries = generate_synthetic_queries(
                    dm, wing=ctx.args[0] if ctx.args else "default", n=int(ctx.flags.get("n", 20))
                )
                out = ctx.out
                out.write(f"Queries sintéticas generadas: {len(queries)}\n")
                for q in queries[:5]:
                    out.write(f"  - {q.query[:60]}... (wing={q.wing})\n")
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory eval synthetic",
            short="Generar queries sintéticas para evaluación",
            flags={"n": Flag("n", shorthand="n", default="20", help="Número de queries a generar")},
            min_args=1,
            max_args=1,
            run=run,
        )
        return cmd

    # Fase 2: Metacognición Avanzada
    def metacog_predict_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.metacog_v2 import MetacognitionV2
            from dxrk.memory.palace import DxrkMemory

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                meta = MetacognitionV2(dm)
                pred = meta.predict(ctx.args[0], wing=ctx.args[1] if len(ctx.args) > 1 else "default")
                out = ctx.out
                out.write("Predicción metacognitiva:\n")
                out.write(f"  Confianza: {pred.confidence:.3f}\n")
                out.write(f"  Dificultad: {pred.difficulty:.3f}\n")
                out.write(f"  ECE: {pred.ece:.3f}\n")
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory metacog predict",
            short="Predicción metacognitiva (confianza, dificultad, ECE)",
            min_args=1,
            max_args=2,
            run=run,
        )
        return cmd

    def metacog_calibrate_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.metacog_v2 import MetacognitionV2
            from dxrk.memory.palace import DxrkMemory

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                meta: MetacognitionV2 = MetacognitionV2(dm)
                result = meta.fit_calibration(
                    wing=ctx.args[0] if ctx.args else "default", method=str(ctx.flags.get("method", "temperature"))
                )
                out = ctx.out
                out.write(f"Calibración ajustada: {ctx.flags.get('method', 'temperature')}\n")
                out.write(f"  Parámetros: {result}\n")
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory metacog calibrate",
            short="Ajustar calibración (temperature scaling o isotonic regression)",
            flags={
                "method": Flag("method", shorthand="m", default="temperature", help="Método: temperature o isotonic")
            },
            min_args=0,
            max_args=1,
            run=run,
        )
        return cmd

    # Fase 2: Multi-Tenant Calibrate
    def calibrate_tenant_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: write op (setting calibration params)
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "write")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.calibrate_v2 import CalibrationParams, save_calibration

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            palace = Path(palace_path)
            params = CalibrationParams(
                tenant=ctx.args[0],
                wing=ctx.args[1],
                a=float(ctx.flags.get("a", 1.0)),
                b=float(ctx.flags.get("b", 0.0)),
                c=float(ctx.flags.get("c", 1.0)),
                pe_lambda=float(ctx.flags.get("pe-lambda", 0.0)),
                score=float(ctx.flags.get("score", 0.5)),
            )
            save_calibration(palace, params)
            out = ctx.out
            out.write(f"Calibración guardada: tenant={ctx.args[0]}, wing={ctx.args[1]}\n")
            return 0

        cmd = Command(
            name="memory calibrate tenant",
            short="Guardar calibración para tenant+wing",
            flags={
                "a": Flag("a", shorthand="a", default="1.0", help="Parámetro a"),
                "b": Flag("b", shorthand="b", default="0.0", help="Parámetro b"),
                "c": Flag("c", shorthand="c", default="1.0", help="Parámetro c"),
                "pe-lambda": Flag("pe-lambda", default="0.0", help="Lambda prediction error"),
                "score": Flag("score", shorthand="s", default="0.5", help="Score de calidad"),
            },
            min_args=2,
            max_args=2,
            run=run,
        )
        return cmd

    def calibrate_chain_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.calibrate_v2 import get_calibration_chain

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            palace = Path(palace_path)
            chain = get_calibration_chain(palace, ctx.args[0], ctx.args[1])
            out = ctx.out
            out.write(f"Cadena de calibración (tenant={ctx.args[0]}, wing={ctx.args[1]}):\n")
            for i, c in enumerate(chain):
                out.write(
                    f"  {i}. tenant={c.tenant}, wing={c.wing}, a={c.a:.3f}, b={c.b:.3f}, c={c.c:.3f}, pe_lambda={c.pe_lambda:.3f}, score={c.score:.3f}\n"
                )
            return 0

        cmd = Command(
            name="memory calibrate chain",
            short="Mostrar cadena de calibración con fallback",
            min_args=2,
            max_args=2,
            run=run,
        )
        return cmd

    # Fase 2: Production Hardening
    def production_circuit_breaker_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            from dxrk.memory.production import get_circuit_breakers

            breakers = get_circuit_breakers()
            out = ctx.out
            out.write("Circuit Breakers:\n")
            for name, cb in breakers.items():
                out.write(f"  {name}: state={cb.state}, failures={cb._failure_count}, successes={cb._success_count}\n")
            return 0

        cmd = Command(
            name="memory production circuit-breaker",
            short="Estado de circuit breakers",
            run=run,
        )
        return cmd

    def production_slo_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.palace import DxrkMemory
            from dxrk.memory.production import check_slo, load_slo_config

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                config = load_slo_config(Path(palace_path))
                result = check_slo(dm, wing=ctx.args[0] if ctx.args else "default", config=config)
                out = ctx.out
                out.write(f"SLO Check: {result.compliant}\n")
                for detail in result.details:
                    out.write(f"  {detail}\n")
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory production slo",
            short="Verificar cumplimiento SLO",
            min_args=0,
            max_args=1,
            run=run,
        )
        return cmd

    def production_rollback_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.palace import DxrkMemory
            from dxrk.memory.production import AutoRollbackManager

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                rollback_mgr = AutoRollbackManager(Path(palace_path))
                result = rollback_mgr.check_regression(wing=ctx.args[0] if ctx.args else "default")
                out = ctx.out
                should_rollback = result.get("should_rollback", False)
                severity = result.get("severity", "none")
                out.write(f"Rollback check: should_rollback={should_rollback}, severity={severity}\n")
                for detail in result.get("details", []):
                    out.write(f"  {detail}\n")
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory production rollback",
            short="Verificar si debe hacer auto-rollback",
            min_args=0,
            max_args=1,
            run=run,
        )
        return cmd

    # Fase 2: Judge Externo Continuo
    def judge_status_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.judge_continuous import load_judge_state

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            state = load_judge_state(Path(palace_path))
            out = ctx.out
            out.write("Judge Continuo:\n")
            out.write(f"  Última ejecución: {state.last_run or 'nunca'}\n")
            out.write(f"  Pasos consecutivos: {state.consecutive_passes}\n")
            out.write(f"  Fallos consecutivos: {state.consecutive_failures}\n")
            out.write(f"  Rollbacks recientes: {len(state.rollback_history)}\n")
            for r in state.rollback_history[-5:]:
                out.write(f"  - {r.get('timestamp', '')} {r.get('wing', '')} {r.get('reason', '')}\n")
            return 0

        cmd = Command(
            name="memory judge status",
            short="Estado del judge externo continuo",
            run=run,
        )
        return cmd

    def judge_run_cmd() -> Command:
        def run(ctx: CommandContext) -> int:
            # RBAC: read op
            try:
                from dxrk.security.enforcement import require_op, resolve_user

                require_op(ctx.tenant_id, resolve_user(), "read")
            except PermissionError as exc:
                ctx.err.write(f"Error: {exc}\n")
                return 1

            import os
            from pathlib import Path

            from dxrk.memory.eval_harness import EvalHarness
            from dxrk.memory.judge_continuous import ContinuousJudge
            from dxrk.memory.palace import DxrkMemory

            palace_path = os.environ.get("DXRK_MEMORY_PATH", str(Path.home() / ".dxrk" / "memory"))
            dm = DxrkMemory(palace_path)
            dm.init()
            try:
                harness = EvalHarness(dm, Path(palace_path) / "eval")
                judge = ContinuousJudge(Path(palace_path), harness, interval_hours=24)
                verdict = judge.run_once()
                out = ctx.out
                out.write(
                    f"Veredicto: passed={verdict.passed}, regression={verdict.regression_detected}, severity={verdict.severity}, auto_rollback={verdict.auto_rollback}\n"
                )
                for detail in verdict.details:
                    out.write(f"  {detail}\n")
            finally:
                dm.close()
            return 0

        cmd = Command(
            name="memory judge run",
            short="Ejecutar ciclo de verificación del judge continuo",
            run=run,
        )
        return cmd

    # Register all subcommands
    reg.add_command(eval_run_cmd())
    reg.add_command(eval_synthetic_cmd())
    reg.add_command(metacog_predict_cmd())
    reg.add_command(metacog_calibrate_cmd())
    reg.add_command(calibrate_tenant_cmd())
    reg.add_command(calibrate_chain_cmd())
    reg.add_command(production_circuit_breaker_cmd())
    reg.add_command(production_slo_cmd())
    reg.add_command(production_rollback_cmd())
    reg.add_command(judge_status_cmd())
    reg.add_command(judge_run_cmd())
