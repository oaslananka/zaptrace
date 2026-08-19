"""Electrical graph queries for ERC rules.

The graph is intentionally small and deterministic: it indexes component-pin
endpoints by canonical net id and lets rules ask topology questions instead of
searching strings in net names.
"""

from __future__ import annotations

from dataclasses import dataclass

from zaptrace.core.models import Design, Net, NetNode, NetType


@dataclass(frozen=True)
class PinEndpoint:
    component_ref: str
    pin_name: str
    net_id: str
    pin_type: str = ""


class ElectricalGraph:
    """Graph view over ``Design.nets`` and component pin assignments."""

    def __init__(self, design: Design) -> None:
        self.design = design
        self.net_nodes: dict[str, list[PinEndpoint]] = {net_id: [] for net_id in design.nets}
        self.component_nets: dict[str, set[str]] = {comp.ref: set() for comp in design.components.values()}
        self.component_nets.update({comp.id: set() for comp in design.components.values()})
        self._build()

    @classmethod
    def from_design(cls, design: Design) -> ElectricalGraph:
        return cls(design)

    def _build(self) -> None:
        for net_id, net in self.design.nets.items():
            for node in net.nodes:
                self._add_endpoint(net_id, node)
        for comp in self.design.components.values():
            for pin_name, pin in comp.pins.items():
                if pin.net and pin.net in self.design.nets:
                    self._add_endpoint(pin.net, NetNode(component_ref=comp.ref, pin_name=pin_name))

        for endpoints in self.net_nodes.values():
            endpoints.sort(key=lambda ep: (ep.component_ref, ep.pin_name, ep.net_id))

    def _add_endpoint(self, net_id: str, node: NetNode) -> None:
        comp = self.design.get_component(node.component_ref)
        pin_type = ""
        if comp is not None and node.pin_name in comp.pins:
            pin_type = comp.pins[node.pin_name].type.value
        endpoint = PinEndpoint(
            component_ref=node.component_ref, pin_name=node.pin_name, net_id=net_id, pin_type=pin_type
        )
        if endpoint not in self.net_nodes.setdefault(net_id, []):
            self.net_nodes[net_id].append(endpoint)
        if comp is not None:
            self.component_nets.setdefault(comp.ref, set()).add(net_id)
            self.component_nets.setdefault(comp.id, set()).add(net_id)

    def endpoints(self, net_id: str) -> list[PinEndpoint]:
        return list(self.net_nodes.get(net_id, []))

    def component_refs_on_net(self, net_id: str) -> set[str]:
        return {endpoint.component_ref for endpoint in self.endpoints(net_id)}

    def nets_for_component(self, component_ref: str) -> set[str]:
        return set(self.component_nets.get(component_ref, set()))

    def net(self, net_id: str) -> Net | None:
        return self.design.nets.get(net_id)

    def is_power_net(self, net_id: str) -> bool:
        net = self.net(net_id)
        return net is not None and net.type in (NetType.POWER, NetType.GROUND)

    def has_resistor_to_power(self, signal_net_id: str, allowed_values: set[str] | None = None) -> bool:
        """Return True if a resistor bridges *signal_net_id* to a power/ground rail.

        ``allowed_values`` restricts which resistor values count (e.g. I2C
        pull-up values); pass ``None`` to accept any value.
        """
        for endpoint in self.endpoints(signal_net_id):
            comp = self.design.get_component(endpoint.component_ref)
            if comp is None:
                continue
            comp_type = comp.type.upper()
            if comp_type not in {"RES", "R", "RESISTOR"}:
                continue
            if allowed_values is not None and comp.value not in allowed_values:
                continue
            other_nets = self.nets_for_component(comp.ref) | self.nets_for_component(comp.id)
            other_nets.discard(signal_net_id)
            if any(self.is_power_net(net_id) for net_id in other_nets):
                return True
        return False
