import { describe, expect, it } from "vitest";

import { piiTypeCategory } from "./pii-type-dict";

describe("группировка подписей типов ПДн", () => {
  it("раскладывает типы по понятным бухгалтеру разделам", () => {
    expect(piiTypeCategory("org_name")).toBe("Стороны и представители");
    expect(piiTypeCategory("inn")).toBe("Реквизиты и счета");
    expect(piiTypeCategory("phone")).toBe("Контакты и адреса");
    expect(piiTypeCategory("contract_amount")).toBe("Договор и условия");
  });

  it("показывает незнакомый пользовательский тип в отдельном разделе", () => {
    expect(piiTypeCategory("custom_vendor_id")).toBe("Другие данные");
  });
});
