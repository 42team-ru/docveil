import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { Section } from "@astryxdesign/core/Section";
import { HStack, StackItem, VStack } from "@astryxdesign/core/Stack";
import { Step, Stepper } from "@astryxdesign/core/Stepper";
import { Heading, Text } from "@astryxdesign/core/Text";

import {
  activePipelineStep,
  pipelineSteps,
  processingSummary,
} from "../../../entity/agent/model/fixtures";
import { AgentStateToken } from "../../../entity/agent/ui/agent-state-token";

const STEP_STATUS = {
  done: "success",
  run: "accent",
  wait: undefined,
} as const;

/** Конвейер агентов: шесть шагов от разбора файла до сборки отчёта. */
export function AgentPipeline() {
  return (
    <Section padding={4}>
      <VStack gap={4}>
        <HStack gap={2} vAlign="center">
          <Heading level={5}>Конвейер агентов</Heading>
          <StackItem size="fill" />
          <Text type="supporting" hasTabularNumbers>
            {processingSummary.progress}
          </Text>
        </HStack>

        <Stepper
          activeStep={activePipelineStep}
          orientation="vertical"
          density="compact"
          label="Ход обработки документа"
        >
          {pipelineSteps.map((step, index) => (
            <Step
              key={step.id}
              step={index}
              label={step.name}
              status={STEP_STATUS[step.state]}
              endContent={
                <HStack gap={2} vAlign="center">
                  <AgentStateToken state={step.state} />
                  <Text type="supporting" color="secondary" hasTabularNumbers>
                    {step.time}
                  </Text>
                </HStack>
              }
            >
              <VStack gap={1.5}>
                <Text type="code" size="sm" color="secondary">
                  {step.agent}
                </Text>
                {step.progress === undefined ? null : (
                  <ProgressBar
                    label={`Прогресс шага «${step.name}»`}
                    isLabelHidden
                    value={step.progress}
                  />
                )}
              </VStack>
            </Step>
          ))}
        </Stepper>
      </VStack>
    </Section>
  );
}
