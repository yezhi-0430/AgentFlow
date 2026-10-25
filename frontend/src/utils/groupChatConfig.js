export function buildGroupChatConfig({ enableLead, leadModel, members, maxTurns = 12 }) {
  return {
    enable_lead: Boolean(enableLead),
    ...(enableLead ? { lead_model: leadModel } : {}),
    members: (members || []).map((member, index) => ({
      name: member.name || `member_${index + 1}`,
      model: member.model,
    })),
    max_turns: maxTurns,
  }
}
