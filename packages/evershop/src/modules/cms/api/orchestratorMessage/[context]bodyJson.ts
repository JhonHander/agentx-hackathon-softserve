import bodyParser from 'body-parser';

export default (request, response, next) => {
  bodyParser.json({ inflate: false, limit: '1mb' })(request, response, next);
};
