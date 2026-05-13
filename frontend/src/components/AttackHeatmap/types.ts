export interface MergedTechnique {
  id: string;
  name: string;
  ruleCount: number;
  alertCount: number;
  ruleNames: string[];
  covered: boolean;
  detected: boolean;
}

export interface MergedTactic {
  id: string;
  shortname: string;
  name: string;
  techniques: MergedTechnique[];
}
