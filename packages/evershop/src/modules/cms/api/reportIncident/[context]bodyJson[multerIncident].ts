import bodyParser from 'body-parser';

export default (request, response, next) => {
  bodyParser.json({ inflate: false, limit: '12mb' })(request, response, next);
};
