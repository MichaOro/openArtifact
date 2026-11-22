/* Guarded access to localStorage for modules: it can be missing or throw (private windows, blocked
 * site data), so every read and write goes through here. The implementation and the names of the
 * keys live in theme.js, which classic scripts use directly. */
const { keys, storage } = window.OpenArtifact;

export const KEYS = keys;
export const readStorage = storage.read;
export const writeStorage = storage.write;
export const removeStorage = storage.remove;

/** The value stored as JSON, or null if there is none or it is unreadable. */
export function readJson(key) {
  try {
    return JSON.parse(readStorage(key));
  } catch {
    return null;
  }
}

export const writeJson = (key, value) => writeStorage(key, JSON.stringify(value));
