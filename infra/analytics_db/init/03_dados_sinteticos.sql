-- Dados inventados, pequenos e conferíveis à mão: o objetivo é que o
-- resultado esperado de cada consulta de referência caiba na cabeça de quem
-- estiver lendo o teste que falhou.

INSERT INTO audit.medico (cdgmedico, crm, nome, espec1, cidade, utc_codigo, cep) VALUES
  (1, 'MG0000001', 'Dra. Alice Ramos',  'NEUROLOGIA',  'BELO HORIZONTE', 101, '30110000'),
  (2, 'SP0000002', 'Dr. Bruno Tavares', 'PSIQUIATRIA', 'SAO PAULO',      202, '01310000'),
  (3, 'MG0000003', 'Dra. Carla Nunes',  'PEDIATRIA',   'UBERLANDIA',     101, '38400000');

INSERT INTO audit.molecula_produto_relacao VALUES
  (10, 1, 1, '1', 'EAS', 'EXTRATO CANNABIS SATIVA'),
  (20, 1, 1, '1', 'EAS', 'CANABIDIOL');

INSERT INTO audit.prescricao (cdgmedico, cdglaboratorio, cdgmarca, cdgconcentracao, cdgapresentacao, cdgforma, px1, data) VALUES
  (1, 'EAS', 10, 1, 1, 1, 30, DATE '2026-07-01'),
  (1, 'EAS', 20, 1, 1, 1, 12, DATE '2026-07-01'),
  (1, 'EAS', 10, 1, 1, 1, 40, DATE '2026-08-01'),
  (2, 'EAS', 10, 1, 1, 1, 25, DATE '2026-08-01'),
  (3, 'EAS', 20, 1, 1, 1, 10, DATE '2026-08-01'),
  (2, 'CON', 10, 1, 1, 1, 50, DATE '2026-08-01');

INSERT INTO audit.rx_cadastro_mais_recente VALUES
  ('MG0000001', 'Dra. Alice Ramos',  'SETOR 01', '1001', 'A', 'ALTA',  'ALTO',  'alice@exemplo.test',  '31999990001'),
  ('SP0000002', 'Dr. Bruno Tavares', 'SETOR 02', '1002', 'B', 'MEDIA', 'MEDIO', 'bruno@exemplo.test',  '11999990002'),
  ('MG0000003', 'Dra. Carla Nunes',  'SETOR 01', '1001', 'C', 'BAIXA', 'BAIXO', 'carla@exemplo.test',  '34999990003');

INSERT INTO audit.rx_visitas (crm_norm, setor, data_da_visita, visita_efetiva, tipo_visita, comentarios) VALUES
  ('MG0000001', 'SETOR 01', TIMESTAMP '2026-08-05 09:30', 'S', 'PRESENCIAL', 'apresentou o estudo de dor cronica'),
  ('MG0000001', 'SETOR 01', TIMESTAMP '2026-08-20 14:00', 'S', 'REMOTA',     'retorno rapido, pediu material'),
  ('SP0000002', 'SETOR 02', TIMESTAMP '2026-08-12 10:00', 'N', 'PRESENCIAL', 'nao conseguiu atender');

INSERT INTO cddd.pdvs VALUES
  (9001, '11111111000191', 'FARMACIA CENTRO',  'RUA A, 100',  'CENTRO', 'BELO HORIZONTE', 'MG', '30110000', 101, 1),
  (9002, '22222222000172', 'DROGARIA SUL',     'AV B, 200',   'SUL',    'SAO PAULO',      'SP', '01310000', 202, 1),
  (9003, '33333333000153', 'FARMACIA BAIRRO',  'RUA C, 300',  'NORTE',  'UBERLANDIA',     'MG', '38400000', 101, 2);

INSERT INTO cddd.canal VALUES
  (1, 'REDE NACIONAL', 'VAREJO', 'REDES'),
  (2, 'INDEPENDENTE',  'VAREJO', 'INDEPENDENTES');

INSERT INTO cddd.vendas_consolidado VALUES
  (DATE '2026-07-10', '9001', '259434', 'EXTRATO 30ML',      12, 3600, 101, 1, 11, 21),
  (DATE '2026-07-18', '9002', '259434', 'EXTRATO 30ML',       8, 2400, 202, 2, 12, 22),
  (DATE '2026-08-05', '9001', '259434', 'EXTRATO 30ML',      20, 6000, 101, 1, 11, 21),
  (DATE '2026-08-06', '9001', '234194', 'ISOLADO 30ML',       5, 1500, 101, 1, 11, 21),
  (DATE '2026-08-22', '9003', '259434', 'EXTRATO 30ML',       7, 2100, 101, 1, 11, 21),
  (DATE '2026-08-28', '9002', '254655', 'ISOLADO 10ML',       3,  750, 202, 2, 12, 22);

INSERT INTO cddd.vw_sellout_mensal VALUES
  (DATE '2026-07-01', '259434', 'EXTRATO 30ML', 20, 15, 1.33),
  (DATE '2026-08-01', '259434', 'EXTRATO 30ML', 27, 20, 1.35),
  (DATE '2026-08-01', '234194', 'ISOLADO 30ML',  5,  4, 1.25),
  (DATE '2026-08-01', '254655', 'ISOLADO 10ML',  3,  5, 0.60);

INSERT INTO cddd.fato_cdd VALUES (DATE '2026-08-01', 0.027);

INSERT INTO cddd.forca_vendas VALUES
  (101, '1', 'TERRITORIO MG CENTRO'),
  (202, '2', 'TERRITORIO SP CAPITAL');

INSERT INTO cddd.scd_ct_territorio VALUES
  (1, 11, NULL),
  (2, 12, NULL),
  (1, 19, DATE '2026-03-31');

INSERT INTO cddd.dim_ct VALUES
  (11, 'CT MG', 'ct.mg@exemplo.test'),
  (12, 'CT SP', 'ct.sp@exemplo.test');

INSERT INTO cddd.dim_gr VALUES (21, 'GR SUDESTE'), (22, 'GR SAO PAULO');

INSERT INTO estoque_redes.vw_estoque_cd_recente VALUES
  ('REDE ALFA', 11111111000191, 'FARMACIA CENTRO', 'PDV', '7896806601250', 14, DATE '2026-09-10'),
  ('REDE ALFA', 11111111000191, 'FARMACIA CENTRO', 'PDV', '7896806601243',  6, DATE '2026-09-10'),
  ('REDE BETA', 22222222000172, 'DROGARIA SUL',    'PDV', '7896806601250',  0, DATE '2026-09-11'),
  ('REDE ALFA', 44444444000114, 'CD ALFA',         'CD',  '7896806601250', 900, DATE '2026-09-11');

INSERT INTO estoque_redes.vw_forecast_projecao_cd_extrato VALUES
  ('REDE ALFA', 'CD ALFA', 900, 18, 0,   false, 0),
  ('REDE BETA', 'CD BETA',  40,  3, 600, true,  0),
  ('REDE BETA', 'CD BETA',  10,  1, 600, true,  1);

INSERT INTO ruptura_extrato.vw_app_pdvs VALUES
  ('FARMACIA CENTRO', 'REDE ALFA', 'RUA A, 100', 'BELO HORIZONTE', 'MG', '3133330001', 14, -19.9191, -43.9386),
  ('FARMACIA BAIRRO', 'REDE GAMA', 'RUA C, 300', 'UBERLANDIA',     'MG', '3433330003',  4, -18.9186, -48.2772);

INSERT INTO ruptura_extrato.dim_cep_geo VALUES
  ('30110000', -19.9200, -43.9400),
  ('38400000', -18.9180, -48.2770);

INSERT INTO ruptura_extrato.vw_representantes_ativos VALUES
  ('1', 'TERRITORIO MG CENTRO', 'CT MG', 'ct.mg@exemplo.test'),
  ('2', 'TERRITORIO SP CAPITAL', 'CT SP', 'ct.sp@exemplo.test');


-- Uma transação cancelada e uma com profissional não informado ("0"), para
-- os filtros das referências Q30-Q32 terem o que descartar.
INSERT INTO pbm.fato_pbm_transacoes VALUES
  ('CONFIRMADA', DATE '2026-08-03', '7896806601250', 'EXTRATO', '4', '0', '11111111000191', 'FARMACIA CENTRO', 'BELO HORIZONTE', 'MG', 'MG', '0000001', 'Dra. Alice Ramos', '00000000001', 'Consumidor Um', 'um@exemplo.test', '31988880001'),
  ('CONFIRMADA', DATE '2026-08-19', '7896806601243', 'ISOLADO', '2', '1', '11111111000191', 'FARMACIA CENTRO', 'BELO HORIZONTE', 'MG', 'MG', '0000001', 'Dra. Alice Ramos', '00000000002', 'Consumidor Dois', 'dois@exemplo.test', '31988880002'),
  ('CANCELADA', DATE '2026-08-20', '7896806601250', 'EXTRATO', '9', '0', '22222222000172', 'DROGARIA SUL', 'SAO PAULO', 'SP', 'SP', '0000002', 'Dr. Bruno Tavares', '00000000003', 'Consumidor Tres', 'tres@exemplo.test', '11988880003'),
  ('CONFIRMADA', DATE '2026-08-25', '7896806601250', 'EXTRATO', '5', '0', '22222222000172', 'DROGARIA SUL', 'SAO PAULO', 'SP', 'SP', '0', 'NAO INFORMADO', '00000000004', 'Consumidor Quatro', 'quatro@exemplo.test', '11988880004');

INSERT INTO tdd.dim_pdv VALUES
  (9001, 11111111000191, 'FARMACIA CENTRO', 'BELO HORIZONTE', 'MG', 101),
  (9002, 22222222000172, 'DROGARIA SUL', 'SAO PAULO', 'SP', 202);

INSERT INTO tdd.fato_tdd VALUES
  (9001, 3, 'TRIM01_202506', 2, 120, 36000),
  (9001, 3, 'TRIM02_202509', 1, 180, 54000),
  (9002, 3, 'TRIM02_202509', 4, 60, 18000),
  (9001, 1, 'TRIM02_202509', 8, 10, 3000);
