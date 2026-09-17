/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { useEffect, useMemo, useState } from 'react';
import { t } from '@apache-superset/core/translation';
import { SupersetClient } from '@superset-ui/core';
import {
  Alert,
  Button,
  Card,
  Select,
  Space,
  Typography,
} from '@superset-ui/core/components';

type AtScaleModel = {
  table_catalog: string;
  table_schema: string;
  table_name: string;
  name?: string;
  description?: string;
};

type ModelColumn = {
  column_name?: string;
  role?: string;
  data_type?: string;
  column_remark?: string;
};

type ModelMetadata = ModelColumn[];

const ADAPTER_BASE = '/extensions/pentland/atscale-mcp-adapter';

export default function AtScaleModelSelector() {
  const [models, setModels] = useState<AtScaleModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<AtScaleModel>();
  const [metadata, setMetadata] = useState<ModelMetadata>();
  const [loadingModels, setLoadingModels] = useState(true);
  const [loadingMetadata, setLoadingMetadata] = useState(false);
  const [error, setError] = useState<string>();
  const [creatingDataset, setCreatingDataset] = useState(false);

  useEffect(() => {
    let active = true;
    setLoadingModels(true);
    SupersetClient.get({ endpoint: `${ADAPTER_BASE}/models` })
      .then(({ json }) => {
        const result = json.result as unknown;
        const discoveredModels = Array.isArray(result)
          ? (result as AtScaleModel[])
          : [];
        if (active) {
          setModels(discoveredModels);
          setSelectedModel(discoveredModels[0]);
          setError(undefined);
        }
      })
      .catch((requestError: Error) => {
        if (active) {
          setError(requestError.message || t('Unable to load AtScale models'));
        }
      })
      .finally(() => active && setLoadingModels(false));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedModel) {
      setMetadata(undefined);
      return undefined;
    }
    let active = true;
    setLoadingMetadata(true);
    const query = new URLSearchParams({
      catalog: selectedModel.table_catalog,
      schema: selectedModel.table_schema,
      table: selectedModel.table_name,
    });
    SupersetClient.get({ endpoint: `${ADAPTER_BASE}/model?${query}` })
      .then(({ json }) => {
        if (active) setMetadata(json.result as ModelMetadata);
      })
      .catch((requestError: Error) => {
        if (active) setError(requestError.message || t('Unable to load model metadata'));
      })
      .finally(() => active && setLoadingMetadata(false));
    return () => {
      active = false;
    };
  }, [selectedModel]);

  const columns = useMemo(() => metadata || [], [metadata]);
  const measures = columns.filter(column => column.role?.toLowerCase() === 'measure');
  const dimensions = columns.filter(column => column.role?.toLowerCase() === 'dimension');

  const renderColumnNames = (items: ModelColumn[]) =>
    items.length > 0
      ? items
          .map(column => column.column_name)
          .filter((name): name is string => Boolean(name))
          .join(', ')
      : t('None returned by AtScale');

  const createAndExplore = () => {
    if (!selectedModel) return;
    setCreatingDataset(true);
    SupersetClient.post({
      endpoint: `${ADAPTER_BASE}/dataset`,
      jsonPayload: { model: selectedModel.name || selectedModel.table_name },
    })
      .then(({ json }) => {
        const result = json.result as { explore_url?: string };
        if (result.explore_url) window.location.assign(result.explore_url);
      })
      .catch((requestError: Error) =>
        setError(requestError.message || t('Unable to create AtScale dataset')),
      )
      .finally(() => setCreatingDataset(false));
  };

  return (
    <Card title={t('AtScale semantic models')} loading={loadingModels}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {error && (
          <Alert
            closable
            message={t('AtScale connection unavailable')}
            description={error}
            type="error"
          />
        )}
        <Select
          ariaLabel={t('Select an AtScale semantic model')}
          loading={loadingModels}
          options={models.map(model => ({
            label: model.name || model.table_name,
            value: `${model.table_catalog}.${model.table_schema}.${model.table_name}`,
          }))}
          placeholder={t('Select a semantic model')}
          showSearch
          value={
            selectedModel &&
            `${selectedModel.table_catalog}.${selectedModel.table_schema}.${selectedModel.table_name}`
          }
          onChange={value =>
            setSelectedModel(
              models.find(
                model =>
                  `${model.table_catalog}.${model.table_schema}.${model.table_name}` === value,
              ),
            )
          }
        />
        {selectedModel && (
          <Space direction="vertical" size="small">
            <Typography.Text strong>{selectedModel.name || selectedModel.table_name}</Typography.Text>
            <Typography.Text type="secondary">
              {loadingMetadata
                ? t('Loading governed measures and dimensions...')
                : t('%s measures · %s dimensions', measures.length, dimensions.length)}
            </Typography.Text>
            {!loadingMetadata && (
              <Space direction="vertical" size="small">
                <Typography.Text>
                  <strong>{t('Measures:')}</strong> {renderColumnNames(measures)}
                </Typography.Text>
                <Typography.Text>
                  <strong>{t('Dimensions:')}</strong> {renderColumnNames(dimensions)}
                </Typography.Text>
              </Space>
            )}
            <Button loading={creatingDataset} onClick={createAndExplore} type="primary">
              {t('Create and explore model')}
            </Button>
          </Space>
        )}
      </Space>
    </Card>
  );
}
