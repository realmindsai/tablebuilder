// src/shared/abs/types.ts

export interface Input {
  dataset: string;
  rows: string[];
  columns: string[];
  wafers?: string[];
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
