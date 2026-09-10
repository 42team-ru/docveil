export type PasswordStrength = {
  score: number;
  max: number;
  label: string;
  variant: "error" | "warning" | "success";
  hasMinLength: boolean;
  hasDigit: boolean;
  hasLetter: boolean;
};

const MAX_SCORE = 5;

/** Насколько надёжен новый пароль — для индикатора в разделе смены пароля. */
export function evaluatePasswordStrength(password: string): PasswordStrength {
  const hasMinLength = password.length >= 8;
  const hasDigit = /[0-9]/.test(password);
  const hasLetter = /[a-zA-Zа-яА-Я]/.test(password);
  const hasLongLength = password.length >= 12;
  const hasSymbol = /[^a-zA-Zа-яА-Я0-9]/.test(password);

  const score = [hasMinLength, hasDigit, hasLetter, hasLongLength, hasSymbol].filter(
    Boolean,
  ).length;

  const variant = score <= 2 ? "error" : score <= 3 ? "warning" : "success";
  const label = score <= 2 ? "Слабый пароль" : score <= 3 ? "Средний пароль" : "Надёжный пароль";

  return { score, max: MAX_SCORE, label, variant, hasMinLength, hasDigit, hasLetter };
}
