from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema
from vaaniflow.domain.schemas.semantic import TaxTreatment


class TaxComponent(DomainSchema):
    """One tax component, such as CGST or SGST."""

    name: str = Field(min_length=1)
    rate: Decimal = Field(ge=0)
    amount: Decimal = Field(ge=0)


class TaxCalculation(DomainSchema):
    """
    Deterministic result of a business tax rule calculation.

    Tax is calculated by the business rules layer, never hallucinated by LLMs.
    """

    taxable_amount: Decimal = Field(ge=0)
    components: list[TaxComponent] = Field(default_factory=list)
    total_tax: Decimal = Field(ge=0)
    total_amount: Decimal = Field(ge=0)
    treatment: TaxTreatment
    rule_version: str = Field(min_length=1)
    provenance: str = Field(min_length=1)


class TaxRule(DomainSchema):
    """
    Business tax rule governing goods/services tax in a given jurisdiction.
    """

    rule_id: UUID
    category: str = Field(min_length=1)
    jurisdiction: str = Field(min_length=1)
    components: dict[str, Decimal] = Field(min_length=1)
    version: str = Field(min_length=1)
    effective_from: date | None = None
    effective_until: date | None = None

    def calculate(
        self,
        taxable_amount: Decimal,
        treatment: TaxTreatment = TaxTreatment.EXCLUSIVE,
    ) -> TaxCalculation:
        """
        Calculate tax components and totals given a taxable amount and treatment.
        """
        quantize_2dp = Decimal("0.01")
        total_rate = sum(self.components.values())

        if treatment == TaxTreatment.INCLUSIVE:
            base_amount = (taxable_amount / (Decimal(1) + total_rate)).quantize(
                quantize_2dp, rounding=ROUND_HALF_UP
            )
        else:
            base_amount = taxable_amount.quantize(quantize_2dp, rounding=ROUND_HALF_UP)

        calc_components: list[TaxComponent] = []
        for name, rate in self.components.items():
            comp_amount = (base_amount * rate).quantize(quantize_2dp, rounding=ROUND_HALF_UP)
            calc_components.append(TaxComponent(name=name, rate=rate, amount=comp_amount))

        actual_total_tax = sum((c.amount for c in calc_components), Decimal(0))
        final_total = base_amount + actual_total_tax

        return TaxCalculation(
            taxable_amount=base_amount,
            components=calc_components,
            total_tax=actual_total_tax,
            total_amount=final_total,
            treatment=treatment,
            rule_version=self.version,
            provenance=f"TaxRule[{self.category}:{self.jurisdiction}:{self.version}]",
        )
