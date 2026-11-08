"""Escrowed bilateral trades: acceptance and settlement are one atomic operation."""
from __future__ import annotations

from typing import Any

from core.actions import ActionRejected
from core.state import GameState, relation_key


class Diplomacy:
    def __init__(self, state: GameState) -> None:
        self.state = state

    def relation(self, left: str, right: str) -> int:
        return int(self.state.relations.get(relation_key(left, right), 0))

    def change_relation(self, left: str, right: str, delta: int) -> int:
        key = relation_key(left, right)
        self.state.relations[key] = max(-100, min(100, self.relation(left, right) + delta))
        for country_id, other in ((left, right), (right, left)):
            contacts = self.state.countries[country_id].contacts
            if other not in contacts:
                contacts.append(other)
        return self.state.relations[key]

    def gift(self, actor: str, action: dict) -> dict:
        target_id = action["target"]
        if target_id == actor:
            raise ActionRejected("SELF_DIPLOMACY", "不能向本国赠礼")
        if target_id not in self.state.countries:
            raise ActionRejected("UNKNOWN_COUNTRY", "目标国家不存在")
        sender = self.state.countries[actor]
        target = self.state.countries[target_id]
        amount = action["amount"]
        if sender.treasury + 1e-9 < amount:
            raise ActionRejected("INSUFFICIENT_TREASURY", "赠礼金额超过可用财政")
        sender.treasury -= amount
        target.treasury += amount
        delta = max(1, min(20, int(round(amount / 2))))
        relation = self.change_relation(actor, target_id, delta)
        self.state.record(
            "diplomatic_gift", sender=actor, target=target_id,
            amount=amount, relation=relation,
        )
        return {"target": target_id, "amount": amount, "relation": relation}

    def declare_war(self, actor: str, target_id: str) -> dict:
        if target_id == actor:
            raise ActionRejected("SELF_DIPLOMACY", "不能向本国宣战")
        if target_id not in self.state.countries:
            raise ActionRejected("UNKNOWN_COUNTRY", "目标国家不存在")
        attacker = self.state.countries[actor]
        defender = self.state.countries[target_id]
        if target_id in attacker.at_war_with:
            raise ActionRejected("ALREADY_AT_WAR", "双方已经处于战争状态")
        attacker.at_war_with.append(target_id)
        defender.at_war_with.append(actor)
        self.change_relation(actor, target_id, -100)
        for pact in self.state.pacts.values():
            if pact["status"] == "ACTIVE" and {pact["sender"], pact["target"]} == {actor, target_id}:
                pact["status"] = "BROKEN"
        self.state.record("war_declared", attacker=actor, defender=target_id)
        return {"attacker": actor, "defender": target_id, "relation": -100}

    def propose_peace(self, actor: str, target_id: str) -> dict:
        if target_id not in self.state.countries or target_id == actor:
            raise ActionRejected("UNKNOWN_COUNTRY", "目标国家无效")
        if target_id not in self.state.countries[actor].at_war_with:
            raise ActionRejected("NOT_AT_WAR", "双方并未交战")
        for proposal in self.state.diplomatic_proposals.values():
            if proposal["status"] == "PENDING" and proposal["pact"] == "PEACE" and {
                proposal["sender"], proposal["target"]
            } == {actor, target_id}:
                raise ActionRejected("PEACE_PENDING", "已有待回应的和平提案")
        proposal_id = f"D{self.state.next_diplomacy_number:06d}"
        self.state.next_diplomacy_number += 1
        proposal = {
            "proposal_id": proposal_id, "sender": actor, "target": target_id,
            "pact": "PEACE", "status": "PENDING",
            "created_day": self.state.day_index,
            "expires_day": self.state.day_index + self.state.config["trade_expiry_days"],
        }
        self.state.diplomatic_proposals[proposal_id] = proposal
        self.state.record("peace_proposed", **proposal)
        return proposal

    def propose_pact(self, actor: str, action: dict) -> dict:
        target_id = action["target"]
        if target_id == actor:
            raise ActionRejected("SELF_DIPLOMACY", "不能与本国签订协定")
        if target_id not in self.state.countries:
            raise ActionRejected("UNKNOWN_COUNTRY", "目标国家不存在")
        if target_id in self.state.countries[actor].at_war_with:
            raise ActionRejected("AT_WAR", "交战中不能签订贸易协定")
        relation = self.relation(actor, target_id)
        if relation < 15:
            raise ActionRejected("RELATION_TOO_LOW", "关系低于 15，需先改善外交关系")
        for pact in self.state.pacts.values():
            if pact["status"] == "ACTIVE" and pact["pact"] == action["pact"] and {
                pact["sender"], pact["target"]
            } == {actor, target_id}:
                raise ActionRejected("PACT_EXISTS", "双方已有同类有效协定")
        for proposal in self.state.diplomatic_proposals.values():
            if proposal["status"] == "PENDING" and {
                proposal["sender"], proposal["target"]
            } == {actor, target_id}:
                raise ActionRejected("PACT_PENDING", "已有待回应的同类提案")
        proposal_id = f"D{self.state.next_diplomacy_number:06d}"
        self.state.next_diplomacy_number += 1
        proposal = {
            "proposal_id": proposal_id, "sender": actor, "target": target_id,
            "pact": action["pact"], "status": "PENDING",
            "created_day": self.state.day_index,
            "expires_day": self.state.day_index + self.state.config["trade_expiry_days"],
        }
        self.state.diplomatic_proposals[proposal_id] = proposal
        self.change_relation(actor, target_id, 0)
        self.state.record("pact_proposed", **proposal)
        return proposal

    def respond_pact(self, actor: str, action: dict) -> dict:
        proposal = self.state.diplomatic_proposals.get(action["proposal_id"])
        if proposal is None:
            raise ActionRejected("UNKNOWN_PACT", "协定提案不存在")
        if proposal["target"] != actor:
            raise ActionRejected("PERMISSION_DENIED", "只有接收国可以回应协定")
        if proposal["status"] != "PENDING":
            raise ActionRejected("PACT_NOT_PENDING", "协定提案已结束")
        if self.state.day_index >= proposal["expires_day"]:
            proposal["status"] = "EXPIRED"
            raise ActionRejected("PACT_EXPIRED", "协定提案已过期")
        if action["operation"] == "ACCEPT_PACT":
            proposal["status"] = "ACCEPTED"
            proposal["resolved_day"] = self.state.day_index
            if proposal["pact"] == "PEACE":
                sender = self.state.countries[proposal["sender"]]
                target = self.state.countries[actor]
                sender.at_war_with = [cid for cid in sender.at_war_with if cid != actor]
                target.at_war_with = [cid for cid in target.at_war_with if cid != proposal["sender"]]
                sender.war_exhaustion = max(0.0, sender.war_exhaustion - 2.0)
                target.war_exhaustion = max(0.0, target.war_exhaustion - 2.0)
                relation = self.change_relation(actor, proposal["sender"], 20)
                self.state.record(
                    "peace_accepted", sender=proposal["sender"], target=actor, relation=relation,
                )
                return {**proposal, "relation": relation}
            proposal["status"] = "ACTIVE"
            self.state.pacts[proposal["proposal_id"]] = dict(proposal)
            relation = self.change_relation(actor, proposal["sender"], 10)
            self.state.record(
                "pact_accepted", proposal_id=proposal["proposal_id"],
                sender=proposal["sender"], target=actor,
                pact=proposal["pact"], relation=relation,
            )
            return {**proposal, "relation": relation}
        proposal["status"] = "REJECTED"
        proposal["resolved_day"] = self.state.day_index
        self.change_relation(actor, proposal["sender"], -2)
        self.state.record("pact_rejected", proposal_id=proposal["proposal_id"], actor=actor)
        return proposal

    def expire_proposals(self) -> None:
        for proposal in self.state.diplomatic_proposals.values():
            if proposal["status"] == "PENDING" and self.state.day_index >= proposal["expires_day"]:
                proposal["status"] = "EXPIRED"
                self.state.record("pact_expired", proposal_id=proposal["proposal_id"])

    def active_trade_pacts(self, country_id: str) -> int:
        return sum(
            1 for pact in self.state.pacts.values()
            if pact["status"] == "ACTIVE" and pact["pact"] == "TRADE"
            and country_id in (pact["sender"], pact["target"])
        )

    def propose(self, actor: str, action: dict[str, Any]) -> dict[str, Any]:
        target_id = action["target"]
        if target_id == actor:
            raise ActionRejected("SELF_TRADE", "不能与本国交易")
        if target_id not in self.state.countries:
            raise ActionRejected("UNKNOWN_COUNTRY", f"目标国家不存在: {target_id}")
        sender = self.state.countries[actor]
        if target_id in sender.at_war_with:
            raise ActionRejected("AT_WAR", "交战中不能发起贸易")
        offer = action["offer_food"]
        if sender.food + 1e-9 < offer:
            raise ActionRejected("INSUFFICIENT_FOOD", "可用于托管的粮食不足")
        proposal_id = f"T{self.state.next_trade_number:06d}"
        self.state.next_trade_number += 1
        sender.food -= offer
        trade = {
            "proposal_id": proposal_id,
            "sender": actor,
            "target": target_id,
            "offer_food": offer,
            "request_treasury": action["request_treasury"],
            "status": "PENDING",
            "created_day": self.state.day_index,
            "expires_day": self.state.day_index + self.state.config["trade_expiry_days"],
            "resolved_day": None,
        }
        self.state.trades[proposal_id] = trade
        for country_id in (actor, target_id):
            contacts = self.state.countries[country_id].contacts
            other = target_id if country_id == actor else actor
            if other not in contacts:
                contacts.append(other)
        self.state.record("trade_proposed", **trade)
        return {
            "proposal_id": proposal_id,
            "status": "PENDING",
            "escrow_food": offer,
            "expires_day": trade["expires_day"],
        }

    def respond(self, actor: str, action: dict[str, Any]) -> dict[str, Any]:
        proposal_id = action["proposal_id"]
        trade = self.state.trades.get(proposal_id)
        if trade is None:
            raise ActionRejected("UNKNOWN_TRADE", "交易提议不存在")
        if trade["target"] != actor:
            raise ActionRejected("PERMISSION_DENIED", "只有交易接收国可以回应该提议")
        if trade["status"] != "PENDING":
            raise ActionRejected("TRADE_NOT_PENDING", f"交易当前状态为 {trade['status']}")
        if self.state.day_index >= trade["expires_day"]:
            self.expire(trade)
            raise ActionRejected("TRADE_EXPIRED", "交易提议已过期")
        operation = action["operation"]
        sender = self.state.countries[trade["sender"]]
        target = self.state.countries[actor]
        if operation == "REJECT":
            sender.food += trade["offer_food"]
            trade["status"] = "REJECTED"
            trade["resolved_day"] = self.state.day_index
            self.change_relation(actor, trade["sender"], -2)
            self.state.record("trade_rejected", proposal_id=proposal_id, actor=actor)
            return {"proposal_id": proposal_id, "status": "REJECTED", "escrow_refunded": True}

        if trade["sender"] in target.at_war_with:
            raise ActionRejected("AT_WAR", "交战中不能接受贸易")
        requested = trade["request_treasury"]
        if target.treasury + 1e-9 < requested:
            raise ActionRejected("INSUFFICIENT_TREASURY", "接收国财政不足，交易未结算")
        # All checks precede these mutations. The offered food is already in escrow.
        target.treasury -= requested
        sender.treasury += requested
        target.food += trade["offer_food"]
        trade["status"] = "ACCEPTED"
        trade["resolved_day"] = self.state.day_index
        relation = self.change_relation(actor, trade["sender"], 6)
        self.state.record(
            "trade_accepted",
            proposal_id=proposal_id,
            sender=trade["sender"],
            target=actor,
            food=trade["offer_food"],
            treasury=requested,
        )
        return {
            "proposal_id": proposal_id,
            "status": "ACCEPTED",
            "food_transferred": trade["offer_food"],
            "treasury_transferred": requested,
        }

    def expire(self, trade: dict[str, Any]) -> None:
        if trade["status"] != "PENDING":
            return
        sender = self.state.countries[trade["sender"]]
        sender.food += trade["offer_food"]
        trade["status"] = "EXPIRED"
        trade["resolved_day"] = self.state.day_index
        self.state.record("trade_expired", proposal_id=trade["proposal_id"])

    def expire_due(self) -> None:
        for trade in self.state.trades.values():
            if trade["status"] == "PENDING" and self.state.day_index >= trade["expires_day"]:
                self.expire(trade)
