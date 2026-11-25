/* The rule schema of the card rules (ADR-071) as the rule builder takes it: the server's fields and actions
 * (`GET /api/rules/schemas/lane` and `/board`) with their texts from the dictionary, the settings of the actions that have
 * some (a label's text and tone, a colour's tone and mode) and, for the board, its lanes as the choices of the field
 * "Lane". Without a DOM, so it is tested alone. */
import { TONES } from "./card-marks.js";
import { t } from "../i18n.js";

const keyOf = (fieldKey) => fieldKey.replace(/\.$/, "").replace(/\./g, "_");
const toneOptions = () => TONES.map((tone) => ({ value: tone, label: t(`cards_rules.tone.${tone}`) }));

/** The settings each action takes, with their defaults (what a new rule of that action starts with). */
const PARAMS = {
  label: {
    defaults: { text: "", tone: "blue" },
    params: () => [
      { key: "text", kind: "text", label: t("cards_rules.param.text"), max: 24 },
      { key: "tone", kind: "choice", label: t("cards_rules.param.tone"), options: toneOptions() },
    ],
  },
  colour: {
    defaults: { tone: "green", mode: "fill" },
    params: () => [
      { key: "tone", kind: "choice", label: t("cards_rules.param.tone"), options: toneOptions() },
      {
        key: "mode",
        kind: "choice",
        label: t("cards_rules.param.mode"),
        options: [
          { value: "fill", label: t("cards_rules.mode.fill") },
          { value: "border", label: t("cards_rules.mode.border") },
        ],
      },
    ],
  },
};

/**
 * @param {{fields: object[], consequences: {key: string, available: boolean}[]}} server the schema of the purpose
 * @param {{lanes?: {status: string, title: string}[]}} [options] the board's lanes (for the field "Lane" of the board's rules)
 */
export function buildSchema(server, { lanes = [] } = {}) {
  return {
    actions: server.consequences
      .filter((c) => c.available)
      .map((c) => ({
        key: c.key,
        label: t(`cards_rules.action.${c.key}`),
        phrase: t(`cards_rules.phrase.${c.key}`),
        effect: c.key === "delete" ? "deletes" : c.key === "archive" ? "hides" : "",
        startsOff: c.key === "delete", // a rule that deletes starts switched off (ADR-071)
        defaults: PARAMS[c.key]?.defaults,
        params: PARAMS[c.key]?.params(),
      })),
    fields: server.fields.map((f) => {
      const field = {
        key: f.key,
        prefix: f.prefix ?? undefined,
        kind: f.key === "lane" ? "choice" : f.kind,
        label: t(`cards_rules.field.${keyOf(f.key)}`),
        minimum: f.minimum,
        units: f.units,
        default: f.kind === "duration" ? 604800 : 0,
        options: f.key === "lane" ? lanes.map((l) => ({ value: l.status, label: l.title })) : f.options.map((o) => ({ value: o, label: t(`cards_rules.option.${o}`) })),
        operators: f.operators.map((o) => ({ key: o, label: t(`cards_rules.operator.${o}`) })),
      };
      if (field.prefix) field.placeholder = t("cards_rules.field_name");
      return field;
    }),
  };
}
