"""Atalhos conferidos nos .shed.yml; presença aqui não certifica execução científica."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    category: str
    name: str
    owner: str
    description: str


CATALOG = (
    Preset('fastqc', 'FastQC', 'Qualidade', 'fastqc', 'devteam', 'Relatórios de qualidade de leituras.'),
    Preset('multiqc', 'MultiQC', 'Qualidade', 'multiqc', 'iuc', 'Agrega relatórios de várias amostras.'),
    Preset('fastp', 'fastp', 'Preparo de leituras', 'fastp', 'iuc', 'Controle de qualidade e pré-processamento FASTQ.'),
    Preset('cutadapt', 'Cutadapt', 'Preparo de leituras', 'cutadapt', 'lparsons', 'Remove adaptadores e filtra leituras.'),
    Preset('trimmomatic', 'Trimmomatic', 'Preparo de leituras', 'trimmomatic', 'pjbriggs', 'Recorte e filtragem de leituras Illumina.'),
    Preset('bowtie2', 'Bowtie 2', 'Alinhamento', 'bowtie2', 'devteam', 'Alinha leituras a uma referência; índices podem exigir downloads extras.'),
    Preset('bwa', 'BWA', 'Alinhamento', 'bwa', 'devteam', 'Wrappers BWA MEM/ALN; referências não são instaladas pelo preset.'),
    Preset('spades', 'SPAdes', 'Montagem', 'spades', 'nml', 'Montagem de genomas; memória e disco dependem dos dados.'),
    Preset('iqtree', 'IQ-TREE', 'Filogenia', 'iqtree', 'iuc', 'Inferência filogenética por máxima verossimilhança.'),
    Preset('qiime2', 'QIIME 2 • Feature Table', 'Microbioma', 'suite_qiime2__feature_table', 'q2d2',
           'Plugin específico do QIIME 2. Wrappers oficiais atuais exigem Docker no destino de jobs do Galaxy.'),
)

BY_ID = {preset.id: preset for preset in CATALOG}
