"""Cross-reference and correlation engine for GSM identification data.

Analyses identification records across operators to detect:
1. Number migration (MSISDN moving between operators)
2. Multi-number subscribers (same PESEL/NIP with different MSISDNs)
3. Data enrichment opportunities (fill gaps from other operators)
4. Identity anomalies (owner of main billing number has other numbers, etc.)

Usage:
    from backend.gsm.identification import IdentificationStore
    from backend.gsm.identification_crossref import CrossReferenceEngine

    store = IdentificationStore()
    store.load_file(...)  # load multiple operator files

    engine = CrossReferenceEngine(store)
    result = engine.analyse(main_msisdn="55082279802")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

from backend.gsm.identification import (
    IdentificationStore,
    SubscriberIdentification,
    normalise_msisdn,
    _record_score,
)

log = logging.getLogger("aistate.gsm.identification_crossref")


# ---------------------------------------------------------------------------
# Data models for cross-reference results
# ---------------------------------------------------------------------------

@dataclass
class MigrationEvent:
    """A single migration event for an MSISDN."""
    msisdn: str = ""
    operator_from: str = ""      # operator that reported "przeniesiony"
    operator_to: str = ""        # operator that has the number now
    date_from: str = ""          # when the number left operator_from
    date_to: str = ""            # when the number appeared at operator_to
    status: str = ""             # "przeniesiony", "aktywny", "dezaktywowany"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OperatorPeriod:
    """Period when an MSISDN was at a specific operator."""
    operator: str = ""
    activation_date: str = ""
    deactivation_date: str = ""
    status: str = ""             # "aktywny", "przeniesiony", "nie_przydzielony"
    name: str = ""               # subscriber name at this operator
    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NumberMigrationHistory:
    """Full migration history for a single MSISDN across operators."""
    msisdn: str = ""
    periods: List[OperatorPeriod] = field(default_factory=list)
    current_operator: str = ""
    migrated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "msisdn": self.msisdn,
            "periods": [p.to_dict() for p in self.periods],
            "current_operator": self.current_operator,
            "migrated": self.migrated,
        }


@dataclass
class IdentityGroup:
    """Group of MSISDNs belonging to the same person/entity (by PESEL or NIP)."""
    identity_key: str = ""       # PESEL or NIP
    identity_type: str = ""      # "pesel" or "nip"
    name: str = ""               # best name
    first_name: str = ""
    last_name: str = ""
    numbers: List[str] = field(default_factory=list)  # MSISDNs
    operators: List[str] = field(default_factory=list)  # unique operators
    entity_type: str = ""        # "person" or "company"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdentityAnomaly:
    """An anomaly detected during cross-reference analysis."""
    anomaly_type: str = ""       # type code
    severity: str = "info"       # "info", "warning", "critical"
    title: str = ""              # short title
    description: str = ""        # detailed description
    msisdn: str = ""             # related MSISDN (if applicable)
    related_msisdns: List[str] = field(default_factory=list)
    pesel: str = ""              # related PESEL (if applicable)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrossReferenceResult:
    """Complete result of cross-reference analysis."""
    identity_groups: List[IdentityGroup] = field(default_factory=list)
    migration_histories: List[NumberMigrationHistory] = field(default_factory=list)
    anomalies: List[IdentityAnomaly] = field(default_factory=list)
    enriched_count: int = 0      # how many records were enriched

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity_groups": [g.to_dict() for g in self.identity_groups],
            "migration_histories": [m.to_dict() for m in self.migration_histories],
            "anomalies": [a.to_dict() for a in self.anomalies],
            "enriched_count": self.enriched_count,
        }


# ---------------------------------------------------------------------------
# Cross-reference engine
# ---------------------------------------------------------------------------

class CrossReferenceEngine:
    """Analyses identification data across operators."""

    def __init__(self, store: IdentificationStore):
        self.store = store

    def analyse(self, main_msisdn: str = "") -> CrossReferenceResult:
        """Run full cross-reference analysis.

        Args:
            main_msisdn: The MSISDN of the main billing subscriber.
                         Used to detect anomalies related to the owner.

        Returns:
            CrossReferenceResult with groups, migrations, and anomalies.
        """
        result = CrossReferenceResult()

        # 1. Enrich records (fill gaps across operators/PESELs)
        self.store.enrich_records()
        # Count is approximate — we don't track exact enrichments
        result.enriched_count = self.store.total_records

        # 2. Build identity groups
        result.identity_groups = self._build_identity_groups()

        # 3. Build migration histories
        result.migration_histories = self._build_migration_histories()

        # 4. Detect anomalies
        result.anomalies = self._detect_anomalies(
            main_msisdn=normalise_msisdn(main_msisdn) if main_msisdn else "",
            identity_groups=result.identity_groups,
            migration_histories=result.migration_histories,
        )

        return result

    def _build_identity_groups(self) -> List[IdentityGroup]:
        """Group MSISDNs by PESEL and NIP."""
        groups: List[IdentityGroup] = []
        seen_keys: Set[str] = set()

        # Group by PESEL
        pesel_groups = self.store.get_pesel_groups()
        for pesel, recs in pesel_groups.items():
            if not pesel or pesel in seen_keys:
                continue
            seen_keys.add(pesel)

            # Collect unique MSISDNs and operators
            msisdns: Set[str] = set()
            operators: Set[str] = set()
            best_rec = max(recs, key=_record_score)

            for rec in recs:
                msisdns.add(rec.number)
                if rec.source_operator:
                    operators.add(rec.source_operator)

            if len(msisdns) < 1:
                continue

            groups.append(IdentityGroup(
                identity_key=pesel,
                identity_type="pesel",
                name=best_rec.name,
                first_name=best_rec.first_name,
                last_name=best_rec.last_name,
                numbers=sorted(msisdns),
                operators=sorted(operators),
                entity_type="person",
            ))

        # Group by NIP (companies)
        nip_groups = self.store.get_nip_groups()
        for nip, recs in nip_groups.items():
            if not nip or nip in seen_keys:
                continue
            seen_keys.add(nip)

            msisdns = set()
            operators = set()
            best_rec = max(recs, key=_record_score)

            for rec in recs:
                msisdns.add(rec.number)
                if rec.source_operator:
                    operators.add(rec.source_operator)

            if len(msisdns) < 1:
                continue

            groups.append(IdentityGroup(
                identity_key=nip,
                identity_type="nip",
                name=best_rec.name,
                first_name=best_rec.first_name,
                last_name=best_rec.last_name,
                numbers=sorted(msisdns),
                operators=sorted(operators),
                entity_type="company",
            ))

        return groups

    def _build_migration_histories(self) -> List[NumberMigrationHistory]:
        """Build migration timeline for each MSISDN that appears at multiple operators."""
        histories: List[NumberMigrationHistory] = []

        for msisdn, recs in self.store._records.items():
            if not recs:
                continue

            # Collect all operator appearances
            operator_records: Dict[str, List[SubscriberIdentification]] = {}
            for rec in recs:
                op = rec.source_operator or "unknown"
                if op not in operator_records:
                    operator_records[op] = []
                operator_records[op].append(rec)

            # Build periods per operator
            periods: List[OperatorPeriod] = []
            has_migration = False

            for op, op_recs in operator_records.items():
                for rec in op_recs:
                    id_type = rec.identification_type

                    if id_type == "other_operator":
                        # This operator says number moved away
                        has_migration = True
                        periods.append(OperatorPeriod(
                            operator=op,
                            activation_date=rec.activation_date,
                            deactivation_date=rec.deactivation_date,
                            status="przeniesiony",
                            name=rec.name,
                            source_file=rec.source_file,
                        ))
                    elif id_type == "not_found":
                        periods.append(OperatorPeriod(
                            operator=op,
                            status="nie_przydzielony",
                            name=rec.name,
                            source_file=rec.source_file,
                        ))
                    else:
                        # Active/historical record at this operator
                        deact = rec.deactivation_date.strip() if rec.deactivation_date else ""
                        is_active = not deact or deact.startswith("9999")
                        periods.append(OperatorPeriod(
                            operator=op,
                            activation_date=rec.activation_date,
                            deactivation_date=rec.deactivation_date,
                            status="aktywny" if is_active else "dezaktywowany",
                            name=rec.name,
                            source_file=rec.source_file,
                        ))

            # Determine if there's meaningful migration
            active_operators = set()
            migrated_operators = set()
            not_assigned_operators = set()

            for p in periods:
                if p.status == "aktywny":
                    active_operators.add(p.operator)
                elif p.status == "przeniesiony":
                    migrated_operators.add(p.operator)
                elif p.status == "nie_przydzielony":
                    not_assigned_operators.add(p.operator)

            # Only include if there's cross-operator activity
            all_ops = active_operators | migrated_operators
            if len(all_ops) < 2 and not has_migration:
                continue

            # Sort periods by activation date
            def _sort_key(p: OperatorPeriod) -> str:
                return p.activation_date or "9999"
            periods.sort(key=_sort_key)

            current_op = ""
            if active_operators:
                current_op = sorted(active_operators)[0]

            histories.append(NumberMigrationHistory(
                msisdn=msisdn,
                periods=periods,
                current_operator=current_op,
                migrated=has_migration or len(all_ops) > 1,
            ))

        return histories

    def _detect_anomalies(
        self,
        main_msisdn: str,
        identity_groups: List[IdentityGroup],
        migration_histories: List[NumberMigrationHistory],
    ) -> List[IdentityAnomaly]:
        """Detect identity-related anomalies."""
        anomalies: List[IdentityAnomaly] = []

        # --- 1. Multi-number owner (same PESEL, multiple numbers) ---
        for group in identity_groups:
            if len(group.numbers) >= 2:
                is_main_owner = main_msisdn and main_msisdn in group.numbers
                other_numbers = [n for n in group.numbers if n != main_msisdn]

                if is_main_owner:
                    anomalies.append(IdentityAnomaly(
                        anomaly_type="multi_number_main_owner",
                        severity="warning",
                        title="Właściciel bilingu ma inne numery",
                        description=(
                            f"Abonent głównego numeru ({main_msisdn}) "
                            f"posiada {len(other_numbers)} inne "
                            f"numer(y): {', '.join(other_numbers)}. "
                            f"Identyfikacja: {group.name} "
                            f"({group.identity_type.upper()}: {group.identity_key})"
                        ),
                        msisdn=main_msisdn,
                        related_msisdns=other_numbers,
                        pesel=group.identity_key if group.identity_type == "pesel" else "",
                        data={
                            "identity_key": group.identity_key,
                            "identity_type": group.identity_type,
                            "name": group.name,
                            "all_numbers": group.numbers,
                            "operators": group.operators,
                        },
                    ))
                else:
                    anomalies.append(IdentityAnomaly(
                        anomaly_type="multi_number_contact",
                        severity="info",
                        title="Kontakt z wieloma numerami",
                        description=(
                            f"{group.name} ({group.identity_type.upper()}: "
                            f"{group.identity_key}) posiada {len(group.numbers)} "
                            f"numer(y): {', '.join(group.numbers)}"
                        ),
                        related_msisdns=group.numbers,
                        pesel=group.identity_key if group.identity_type == "pesel" else "",
                        data={
                            "identity_key": group.identity_key,
                            "identity_type": group.identity_type,
                            "name": group.name,
                            "numbers": group.numbers,
                            "operators": group.operators,
                        },
                    ))

        # --- 2. Number migration events ---
        for history in migration_histories:
            if not history.migrated:
                continue

            # Build a human-readable timeline
            timeline_parts = []
            for p in history.periods:
                if p.status == "przeniesiony":
                    timeline_parts.append(
                        f"{p.operator}: przeniesiony"
                        + (f" (od {p.activation_date})" if p.activation_date else "")
                        + (f" (do {p.deactivation_date})" if p.deactivation_date else "")
                    )
                elif p.status == "aktywny":
                    timeline_parts.append(
                        f"{p.operator}: aktywny"
                        + (f" (od {p.activation_date})" if p.activation_date else "")
                    )
                elif p.status == "nie_przydzielony":
                    timeline_parts.append(f"{p.operator}: nie przydzielony")

            anomalies.append(IdentityAnomaly(
                anomaly_type="number_migration",
                severity="info",
                title=f"Migracja numeru {history.msisdn}",
                description=(
                    f"Numer {history.msisdn} zmieniał operatora. "
                    f"Aktualny: {history.current_operator or 'nieznany'}. "
                    f"Historia: {'; '.join(timeline_parts)}"
                ),
                msisdn=history.msisdn,
                data={
                    "current_operator": history.current_operator,
                    "periods": [p.to_dict() for p in history.periods],
                },
            ))

        # --- 3. Data enrichment events ---
        # Detect cases where one operator had no data but another had full info
        for msisdn, recs in self.store._records.items():
            no_data_ops = set()
            data_ops = set()
            for rec in recs:
                op = rec.source_operator or "unknown"
                if rec.identification_type in ("not_found", "other_operator"):
                    no_data_ops.add(op)
                elif rec.has_owner_data:
                    data_ops.add(op)

            if no_data_ops and data_ops:
                best = self.store.lookup(msisdn)
                if best and best.has_owner_data:
                    anomalies.append(IdentityAnomaly(
                        anomaly_type="data_enriched",
                        severity="info",
                        title=f"Uzupełnione dane dla {msisdn}",
                        description=(
                            f"Numer {msisdn}: brak danych u {', '.join(sorted(no_data_ops))}, "
                            f"ale identyfikacja dostępna u {', '.join(sorted(data_ops))} — "
                            f"{best.name}"
                        ),
                        msisdn=msisdn,
                        data={
                            "no_data_operators": sorted(no_data_ops),
                            "data_operators": sorted(data_ops),
                            "name": best.name,
                            "pesel": best.pesel,
                        },
                    ))

        return anomalies
