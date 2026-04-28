// src/shared/abs/types.ts

export interface VariableRef {
  id: number;
  label: string;
}

export interface Input {
  dataset: string;
  rows: VariableRef[];
  columns: VariableRef[];
  wafers?: VariableRef[];
  geography: VariableRef | null;
  outputPath?: string;
}

export interface Output {
  csvPath: string;
  dataset: string;
  rowCount: number;
}

export interface Credentials {
  userId: string;
  password: string;
}

export type Axis = 'row' | 'col' | 'wafer';
