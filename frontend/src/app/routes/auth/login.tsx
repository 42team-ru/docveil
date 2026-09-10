"use client";

/**
 * THESIS: Корпоративный вход в TriemaMasker — строгий, операционный,
 * без социальных провайдеров. Два пути: логин/пароль AD и LDAP SSO.
 * Отказывается от hero-карточки посередине пустого экрана.
 *
 * OWN-WORLD: Нейтральная тема Astryx, Figtree, нейтральный поверхностный
 * фон с мутной левой панелью-брендингом (Section muted), строгий Card
 * справа. Lucide-иконки, нет произвольных hex/px.
 *
 * STORY: Юрист или менеджер по compliance вводит корпоративные учётные
 * данные и попадает в TriemaMasker за один шаг. LDAP SSO — предпочтительный
 * путь; пароль — резервный.
 *
 * FIRST VIEWPORT: двухколоночный сплит 50/50 на md+. Левая колонка —
 * брендинг и маркеры доверия. Правая — форма входа и кнопка LDAP SSO.
 * На мобильных форма единственная.
 *
 * FORM: SSO-first корпоративный вход с паролем как резервом.
 */

import { useState, type CSSProperties } from "react";
import { useNavigate } from "react-router";
import {
  Building2,
  LogIn,
  Network,
  KeyRound,
  ArrowLeft,
  FileCheck2,
  Users,
  Lock,
} from "lucide-react";
import { VStack } from "@astryxdesign/core/Stack";
import { HStack } from "@astryxdesign/core/HStack";
import { Center } from "@astryxdesign/core/Center";
import { Text, Heading } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Link } from "@astryxdesign/core/Link";
import { Divider } from "@astryxdesign/core/Divider";
import { Icon } from "@astryxdesign/core/Icon";
import { Section } from "@astryxdesign/core/Section";

import { loginApiAuthLoginPost } from "../../../shared/api/generated/core/auth/auth";
import { setAccessToken } from "../../../shared/api/auth-token";

// ─── constants ───────────────────────────────────────────────────────────────

const LDAP_DOMAIN = "corp.triema.ru";

const TRUST_ITEMS = [
  {
    icon: FileCheck2,
    label: "152-ФЗ",
    desc: "Соответствие российскому законодательству о персональных данных",
  },
  {
    icon: Users,
    label: "Корпоративный доступ",
    desc: "Только авторизованные сотрудники вашей организации",
  },
  {
    icon: Lock,
    label: "Локальный контур",
    desc: "Документы не покидают инфраструктуру",
  },
] as const;

// ─── types ───────────────────────────────────────────────────────────────────

type Step = "main" | "ldap-redirect" | "password";

// ─── styles ──────────────────────────────────────────────────────────────────

const formMaxWidth: CSSProperties = {
  width: "100%",
  maxWidth: 400,
};

const LOGIN_CSS = `
.login-split-container {
  display: flex;
  flex-direction: column;
  min-height: 100dvh;
  width: 100%;
}

.login-left-panel {
  display: none;
}

.login-right-panel {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}

@media (min-width: 768px) {
  .login-split-container {
    flex-direction: row;
  }
  .login-left-panel {
    display: flex;
    flex: 0 0 42%;
    flex-direction: column;
  }
}

.mobile-only-brand {
  display: flex;
  text-align: center;
  width: 100%;
  margin-bottom: var(--spacing-6);
}

@media (min-width: 768px) {
  .mobile-only-brand {
    display: none !important;
  }
}
`;

// ─── component ───────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("main");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [loginFailed, setLoginFailed] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleLdapLogin = () => {
    setIsLoading(true);
    // Имитация редиректа на LDAP SSO
    setTimeout(() => {
      setIsLoading(false);
      setStep("ldap-redirect");
    }, 1500);
  };

  /**
   * Вход логином и паролем. Access-токен кладётся в память вкладки, refresh
   * бэкенд ставит httpOnly-cookie сам (`device: "web"`), поэтому обновление
   * сессии дальше идёт без участия этого экрана.
   */
  const handlePasswordLogin = async () => {
    if (!login || !password) {
      setLoginFailed(true);
      return;
    }
    setIsLoading(true);
    setLoginFailed(false);
    try {
      const response = await loginApiAuthLoginPost({
        email: login,
        password,
        device: "web",
      });
      if (response.status !== 200) {
        setLoginFailed(true);
        return;
      }
      setAccessToken(response.data.access_token);
      navigate("/");
    } catch {
      setLoginFailed(true);
    } finally {
      setIsLoading(false);
    }
  };

  const handleBack = () => {
    setStep("main");
    setLoginFailed(false);
    setIsLoading(false);
    setPassword("");
  };

  return (
    <>
      <style>{LOGIN_CSS}</style>
      <div className="login-split-container">
        {/* ── Левая панель: Брендинг и маркеры доверия ── */}
        <Section variant="muted" className="login-left-panel" padding={0}>
          <Center axis="both" padding={10} height="100%">
            <VStack gap={10} width="100%" hAlign="stretch" style={{ maxWidth: 440 }}>
              <VStack gap={4}>
                <HStack gap={3} vAlign="center">
                  <img
                    src="/logo.png"
                    alt="DocVeil"
                    className="size-10 object-contain"
                  />
                  <Heading level={2} className="font-brand">
                    DocVeil
                  </Heading>
                </HStack>
                <Text type="body" color="secondary" size="lg">
                  Автоматическое обезличивание юридических документов в защищенном контуре.
                </Text>
              </VStack>

              <VStack gap={6}>
                {TRUST_ITEMS.map((item, index) => (
                  <HStack key={index} gap={4} vAlign="start">
                    <div style={{ marginTop: "2px" }}>
                      <Icon icon={item.icon} size="md" color="secondary" />
                    </div>
                    <VStack gap={1}>
                      <Text type="body" weight="medium">
                        {item.label}
                      </Text>
                      <Text type="supporting" color="secondary">
                        {item.desc}
                      </Text>
                    </VStack>
                  </HStack>
                ))}
              </VStack>
            </VStack>
          </Center>
        </Section>

        {/* ── Правая панель: форма ── */}
        <Section variant="section" className="login-right-panel" padding={0}>
          <Center axis="both" padding={8} height="100%">
            <VStack gap={8} hAlign="center" style={formMaxWidth}>
              
              {/* Header on mobile only, replacing the missing left panel context */}
              <div className="mobile-only-brand">
                <VStack gap={2} hAlign="center" width="100%">
                  <img
                    src="/logo.png"
                    alt="DocVeil"
                    className="size-8 object-contain"
                  />
                  <Heading level={3} className="font-brand">
                    DocVeil
                  </Heading>
                </VStack>
              </div>

              {/* ── Шаг: главный экран (LDAP + пароль) ── */}
              {step === "main" && (
                <VStack gap={6} hAlign="stretch" width="100%">
                  <VStack gap={1} hAlign="center">
                    <Heading level={1}>Вход в систему</Heading>
                    <Text type="body" color="secondary" size="sm">
                      Используйте корпоративные учётные данные
                    </Text>
                  </VStack>

                  {/* Корпоративный вход LDAP */}
                  <Card padding={6} width="100%">
                    <VStack gap={4} hAlign="stretch">
                      <HStack gap={2} vAlign="center">
                        <Icon icon={Network} size="sm" color="secondary" />
                        <Text type="label" weight="medium">
                          Корпоративный вход (LDAP)
                        </Text>
                      </HStack>
                      <Text type="supporting" color="secondary">
                        Единый вход через корпоративный каталог организации. Не
                        требует отдельного пароля — используются ваши доменные
                        учётные данные.
                      </Text>
                      <Button
                        label="Войти через LDAP"
                        variant="primary"
                        size="lg"
                        icon={<Icon icon={LogIn} size="sm" />}
                        isLoading={isLoading}
                        onClick={handleLdapLogin}
                      />
                    </VStack>
                  </Card>

                  <Divider label="или войдите с паролем" />

                  {/* Ссылка на вход с паролем */}
                  <VStack gap={2} hAlign="stretch">
                    <Button
                      label="Войти с логином и паролем"
                      variant="secondary"
                      size="lg"
                      icon={<Icon icon={KeyRound} size="sm" />}
                      onClick={() => setStep("password")}
                    />
                  </VStack>

                  <VStack hAlign="center">
                    <Text type="supporting" color="secondary">
                      Нет доступа?{" "}
                      <Link href="mailto:it@triema.ru" type="supporting">
                        Обратитесь в IT-отдел
                      </Link>
                    </Text>
                  </VStack>
                </VStack>
              )}

              {/* ── Шаг: LDAP редирект (имитация) ── */}
              {step === "ldap-redirect" && (
                <VStack gap={6} hAlign="stretch" width="100%">
                  <VStack gap={3} hAlign="center">
                    <Icon icon={Network} size="lg" color="primary" />
                    <VStack gap={1} hAlign="center">
                      <Heading level={2}>Перенаправление…</Heading>
                      <Text type="body" color="secondary" size="sm" justify="center">
                        Вы будете перенаправлены на корпоративный портал{" "}
                        <Text type="body" weight="medium" as="span">
                          {LDAP_DOMAIN}
                        </Text>
                      </Text>
                    </VStack>
                  </VStack>

                  <Card padding={6} width="100%">
                    <Section variant="muted" padding={4}>
                      <HStack gap={3} vAlign="center">
                        <Icon icon={Building2} color="secondary" />
                        <VStack gap={0}>
                          <Text type="label">LDAP / Active Directory</Text>
                          <Text type="supporting" color="secondary">
                            {LDAP_DOMAIN}
                          </Text>
                        </VStack>
                      </HStack>
                    </Section>
                  </Card>

                  <VStack gap={3} hAlign="stretch" width="100%">
                    <Button
                      label="Перейти к корпоративному входу"
                      variant="primary"
                      size="lg"
                      isLoading
                      onClick={() => {}}
                    />
                    <Button
                      label="Назад"
                      variant="ghost"
                      size="lg"
                      icon={<Icon icon={ArrowLeft} size="sm" />}
                      onClick={handleBack}
                    />
                  </VStack>
                </VStack>
              )}

              {/* ── Шаг: вход с паролем ── */}
              {step === "password" && (
                <VStack gap={6} hAlign="stretch" width="100%">
                  <VStack gap={1} hAlign="center">
                    <Heading level={2}>Вход с паролем</Heading>
                    <Text type="body" color="secondary" size="sm">
                      Введите корпоративный логин и пароль
                    </Text>
                  </VStack>

                  <VStack gap={4} hAlign="stretch" width="100%">
                    <TextInput
                      label="Логин"
                      type="text"
                      placeholder="Имя пользователя или email"
                      value={login}
                      onChange={(v: string) => {
                        setLogin(v);
                        setLoginFailed(false);
                      }}
                      size="lg"
                    />
                    <VStack gap={2} hAlign="stretch">
                      <TextInput
                        label="Пароль"
                        type="password"
                        placeholder="Корпоративный пароль"
                        value={password}
                        onChange={(v: string) => {
                          setPassword(v);
                          setLoginFailed(false);
                        }}
                        size="lg"
                        status={
                          loginFailed
                            ? {
                                type: "error",
                                message:
                                  "Неверный логин или пароль. Попробуйте ещё раз.",
                              }
                            : undefined
                        }
                      />
                      {loginFailed && (
                        <HStack hAlign="end">
                          <Link
                            href="mailto:it@triema.ru"
                            size="sm"
                            color="secondary"
                            type="supporting"
                          >
                            Забыли пароль? Обратитесь в IT
                          </Link>
                        </HStack>
                      )}
                    </VStack>

                    <Button
                      label="Войти"
                      variant="primary"
                      size="lg"
                      isLoading={isLoading}
                      onClick={() => void handlePasswordLogin()}
                    />

                    <Button
                      label="Назад"
                      variant="ghost"
                      size="lg"
                      icon={<Icon icon={ArrowLeft} size="sm" />}
                      onClick={handleBack}
                    />
                  </VStack>

                  <VStack hAlign="center">
                    <Text type="supporting" color="secondary" justify="center">
                      Рекомендуем использовать{" "}
                      <Link
                        href="#"
                        type="supporting"
                        onClick={(e: React.MouseEvent) => {
                          e.preventDefault();
                          handleBack();
                        }}
                      >
                        корпоративный LDAP-вход
                      </Link>
                    </Text>
                  </VStack>
                </VStack>
              )}
            </VStack>
          </Center>
        </Section>
      </div>
    </>
  );
}
