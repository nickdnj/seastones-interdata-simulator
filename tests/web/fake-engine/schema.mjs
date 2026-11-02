// schema.mjs: validate protocol v1 messages against schema/protocol-v1.json (VS-28).
//
// A deliberately small JSON-Schema subset (type, const, enum, required, properties,
// additionalProperties, patternProperties, items, minItems, maxItems, minimum, maximum,
// pattern, $ref) so the fake engine and the tests need no dependency. `$ref` names a
// key in `definitions`, or `server:<type>` / `client:<type>`.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const SCHEMA_PATH = path.join(HERE, "schema", "protocol-v1.json");
export const SCHEMA = JSON.parse(readFileSync(SCHEMA_PATH, "utf8"));
function resolve(ref) {
  const [side, name] = ref.includes(":") ? ref.split(":") : ["definitions", ref];
  const target = SCHEMA[side] && SCHEMA[side][name];
  if (!target) throw new Error(`schema: unknown $ref ${ref}`);
  return target;
}

function typeOf(v) {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (Number.isInteger(v)) return "integer";
  return typeof v;
}

function typeOk(want, v) {
  const t = typeOf(v);
  const list = Array.isArray(want) ? want : [want];
  return list.some((w) => w === t || (w === "number" && t === "integer"));
}

export function check(schema, value, where = "$", errors = []) {
  if (schema.$ref) return check(resolve(schema.$ref), value, where, errors);
  if ("const" in schema && value !== schema.const) {
    errors.push(`${where}: must be ${JSON.stringify(schema.const)}`);
    return errors;
  }
  if (schema.enum && !schema.enum.includes(value)) {
    errors.push(`${where}: ${JSON.stringify(value)} is not one of ${schema.enum.join(", ")}`);
    return errors;
  }
  if (schema.type && !typeOk(schema.type, value)) {
    errors.push(`${where}: expected ${schema.type}, got ${typeOf(value)}`);
    return errors;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) errors.push(`${where}: not a finite number`);
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${where}: below ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${where}: above ${schema.maximum}`);
  }
  if (typeof value === "string" && schema.pattern && !new RegExp(schema.pattern).test(value)) {
    errors.push(`${where}: ${JSON.stringify(value)} does not match ${schema.pattern}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) errors.push(`${where}: fewer than ${schema.minItems} items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) errors.push(`${where}: more than ${schema.maxItems} items`);
    if (schema.items) value.forEach((item, i) => check(schema.items, item, `${where}[${i}]`, errors));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of schema.required || []) {
      if (!(key in value)) errors.push(`${where}: missing ${key}`);
    }
    const props = schema.properties || {};
    const patterns = Object.entries(schema.patternProperties || {}).map(([p, s]) => [new RegExp(p), s]);
    for (const [key, v] of Object.entries(value)) {
      if (props[key]) check(props[key], v, `${where}.${key}`, errors);
      else {
        const hit = patterns.find(([re]) => re.test(key));
        if (hit) check(hit[1], v, `${where}.${key}`, errors);
        else if (schema.additionalProperties === false) errors.push(`${where}: unexpected key ${key}`);
      }
    }
  }
  return errors;
}

/** Errors for one message. `side` is "server" (rigd to page) or "client" (page to rigd). */
export function validate(side, message) {
  if (!message || typeof message !== "object") return [`not an object`];
  const schema = SCHEMA[side] && SCHEMA[side][message.t];
  if (!schema) return [`unknown ${side} message type ${JSON.stringify(message.t)}`];
  return check(schema, message, message.t);
}

export const clientTypes = () => Object.keys(SCHEMA.client);
export const serverTypes = () => Object.keys(SCHEMA.server);
